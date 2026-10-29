package ai.caseintel.api.service;

import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.config.AppProperties;
import ai.caseintel.api.domain.CaseEntity;
import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.domain.DocumentEntity;
import ai.caseintel.api.domain.ExtractionEntity;
import ai.caseintel.api.domain.FindingEntity;
import ai.caseintel.api.domain.FindingStatus;
import ai.caseintel.api.jobs.JobQueue;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.repo.DocumentRepository;
import ai.caseintel.api.repo.ExtractionRepository;
import ai.caseintel.api.repo.FindingRepository;
import ai.caseintel.api.rules.PackRegistry;
import ai.caseintel.api.service.Dtos.AuditView;
import ai.caseintel.api.service.Dtos.CaseDetail;
import ai.caseintel.api.service.Dtos.CaseSummary;
import ai.caseintel.api.service.Dtos.DocumentView;
import ai.caseintel.api.service.Dtos.ExtractionSummary;
import ai.caseintel.api.service.Dtos.FindingView;
import ai.caseintel.api.service.Dtos.PageView;
import ai.caseintel.api.service.Dtos.UploadResult;
import ai.caseintel.api.storage.FileStorage;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

@Service
public class CaseService {

    private static final Set<CaseStatus> REVIEWABLE =
            Set.of(CaseStatus.NEEDS_REVIEW, CaseStatus.ESCALATED, CaseStatus.AUTO_CLEARED);

    private final CaseRepository cases;
    private final DocumentRepository documents;
    private final ExtractionRepository extractions;
    private final FindingRepository findings;
    private final PackRegistry packs;
    private final JobQueue jobs;
    private final FileStorage storage;
    private final AuditService audit;
    private final UploadRateLimiter rateLimiter;
    private final ProcessingMetrics metrics;
    private final ObjectMapper mapper;
    private final AppProperties props;

    public CaseService(CaseRepository cases, DocumentRepository documents, ExtractionRepository extractions,
                       FindingRepository findings, PackRegistry packs, JobQueue jobs, FileStorage storage,
                       AuditService audit, UploadRateLimiter rateLimiter, ProcessingMetrics metrics,
                       ObjectMapper mapper, AppProperties props) {
        this.cases = cases;
        this.documents = documents;
        this.extractions = extractions;
        this.findings = findings;
        this.packs = packs;
        this.jobs = jobs;
        this.storage = storage;
        this.audit = audit;
        this.rateLimiter = rateLimiter;
        this.metrics = metrics;
        this.mapper = mapper;
        this.props = props;
    }

    private record Incoming(String filename, String mimeType, byte[] bytes, String sha256, Integer pages) {}

    @PreAuthorize("hasRole('ANALYST')")
    @Transactional
    public UploadResult upload(String caseType, String title, String attributes, List<MultipartFile> files,
                               String user) {
        rateLimiter.acquire(user);
        if (packs.find(caseType).isEmpty()) {
            throw ApiException.badRequest("Unknown caseType '" + caseType + "'. Known types: "
                    + packs.all().stream().map(p -> p.code().caseType()).sorted().toList());
        }
        if (files == null || files.isEmpty()) {
            throw ApiException.badRequest("Attach at least one file in the 'files' field.");
        }
        JsonNode attrs = parseAttributes(attributes);
        List<Incoming> incoming = new ArrayList<>();
        for (MultipartFile f : files) {
            incoming.add(read(f));
        }

        String version = props.pipelineVersion();
        Set<String> shas = incoming.stream().map(Incoming::sha256).collect(Collectors.toCollection(LinkedHashSet::new));
        for (UUID candidate : documents.findCaseIdsWithSha(incoming.get(0).sha256(), caseType, version)) {
            Set<String> existing = documents.findByCaseIdOrderByCreatedAt(candidate).stream()
                    .map(DocumentEntity::getSha256).collect(Collectors.toSet());
            // Same files under different attributes is a new case: one statement filed for two applicants is a signal.
            if (existing.equals(shas) && read(load(candidate).getAttributes()).equals(attrs)) {
                metrics.cacheHit();
                audit.record(candidate, user, "UPLOAD_CACHE_HIT", Map.of("sha256", List.copyOf(shas)));
                return new UploadResult(detail(candidate), true);
            }
        }

        Instant now = Instant.now();
        UUID caseId = UUID.randomUUID();
        String caseTitle = title == null || title.isBlank() ? incoming.get(0).filename() : title.trim();
        cases.save(new CaseEntity(caseId, caseType, caseTitle, attrs.toString(), version, user, now));
        List<Map<String, Object>> fileLog = new ArrayList<>();
        for (Incoming in : incoming) {
            Path path = storage.store(in.sha256(), in.bytes());
            documents.save(new DocumentEntity(UUID.randomUUID(), caseId, in.filename(), in.mimeType(), in.sha256(),
                    in.bytes().length, path.toString(), in.pages(), now));
            fileLog.add(Map.of("filename", in.filename(), "sha256", in.sha256(), "sizeBytes", in.bytes().length));
        }
        // The queue insert is plain JDBC, so the JPA rows it references must reach the database first.
        cases.flush();
        jobs.enqueue(caseId, JobQueue.PROCESS_CASE, caseId + ":process:" + version);
        audit.record(caseId, user, "CASE_CREATED",
                Map.of("caseType", caseType, "title", caseTitle, "attributes", attrs, "pipelineVersion", version,
                        "files", fileLog));
        metrics.cacheMiss();
        return new UploadResult(detail(caseId), false);
    }

    private Incoming read(MultipartFile f) {
        byte[] bytes;
        try {
            bytes = f.getBytes();
        } catch (IOException e) {
            throw ApiException.badRequest("Could not read " + f.getOriginalFilename() + ".");
        }
        String name = f.getOriginalFilename() == null || f.getOriginalFilename().isBlank()
                ? "upload" : Path.of(f.getOriginalFilename()).getFileName().toString();
        if (bytes.length == 0) {
            throw ApiException.badRequest(name + " is empty.");
        }
        Integer pages = null;
        if (isPdf(bytes)) {
            try (PDDocument pdf = Loader.loadPDF(bytes)) {
                pages = pdf.getNumberOfPages();
            } catch (IOException e) {
                throw ApiException.unprocessable(name + " looks like a PDF but cannot be opened.");
            }
            int max = props.limits().maxPages();
            if (pages > max) {
                throw ApiException.unprocessable(name + " has " + pages + " pages. The limit is " + max + ".");
            }
        }
        return new Incoming(name, f.getContentType(), bytes, FileStorage.sha256(bytes), pages);
    }

    static boolean isPdf(byte[] bytes) {
        return bytes.length >= 5
                && new String(Arrays.copyOf(bytes, 5), StandardCharsets.US_ASCII).equals("%PDF-");
    }

    @PreAuthorize("hasRole('ANALYST')")
    @Transactional(readOnly = true)
    public Page<CaseSummary> list(CaseStatus status, String caseType, int page, int size) {
        Specification<CaseEntity> spec = (root, q, cb) -> cb.conjunction();
        if (status != null) {
            spec = spec.and((root, q, cb) -> cb.equal(root.get("status"), status));
        }
        if (caseType != null && !caseType.isBlank()) {
            spec = spec.and((root, q, cb) -> cb.equal(root.get("caseType"), caseType));
        }
        Sort sort = Sort.by(Sort.Order.desc("riskScore").nullsLast(), Sort.Order.desc("amountAtRisk").nullsLast(),
                Sort.Order.desc("createdAt"));
        return cases.findAll(spec, PageRequest.of(Math.max(0, page), Math.min(Math.max(1, size), 100), sort))
                .map(this::summary);
    }

    @PreAuthorize("hasRole('ANALYST')")
    @Transactional(readOnly = true)
    public CaseDetail get(UUID id) {
        return detail(id);
    }

    @PreAuthorize("hasRole('ANALYST')")
    @Transactional(readOnly = true)
    public List<PageView> pages(UUID caseId, UUID documentId) {
        DocumentEntity doc = documents.findById(documentId)
                .filter(d -> d.getCaseId().equals(caseId))
                .orElseThrow(() -> ApiException.notFound("Document " + documentId + " is not part of case " + caseId + "."));
        return extractions.findFirstByDocumentIdOrderByCreatedAtDesc(doc.getId())
                .map(e -> {
                    List<PageView> out = new ArrayList<>();
                    read(e.getPayload()).path("pages")
                            .forEach(p -> out.add(new PageView(p.path("page").asInt(), p.path("text").asText())));
                    return out;
                })
                .orElse(List.of());
    }

    @PreAuthorize("hasRole('REVIEWER')")
    @Transactional
    public CaseDetail decideFinding(UUID caseId, UUID findingId, Dtos.FindingDecision d, String user) {
        CaseEntity c = load(caseId);
        requireReviewable(c);
        FindingEntity f = findings.findById(findingId)
                .filter(x -> x.getCaseId().equals(caseId))
                .orElseThrow(() -> ApiException.notFound("Finding " + findingId + " is not part of case " + caseId + "."));
        String action = d.action() == null ? "" : d.action().trim().toUpperCase();
        FindingStatus next = switch (action) {
            case "ACCEPT" -> FindingStatus.ACCEPTED;
            case "DISMISS" -> FindingStatus.DISMISSED;
            case "EDIT" -> FindingStatus.EDITED;
            default -> throw ApiException.badRequest("action must be ACCEPT, DISMISS or EDIT.");
        };
        if (next != FindingStatus.ACCEPTED && isBlank(d.reason())) {
            throw ApiException.badRequest("Give a reason when you " + action.toLowerCase() + " a finding.");
        }
        if (next == FindingStatus.EDITED && d.amount() == null) {
            throw ApiException.badRequest("EDIT needs the corrected amount.");
        }
        FindingStatus previous = f.getStatus();
        f.decide(next, user, d.reason(), next == FindingStatus.EDITED ? d.amount() : null);
        findings.save(f);
        c.setAmountAtRisk(findings.findByCaseIdOrderByWeightDescCreatedAtAsc(caseId).stream()
                .filter(x -> x.getStatus() != FindingStatus.DISMISSED)
                .map(FindingEntity::getAmount).filter(Objects::nonNull)
                .reduce(BigDecimal.ZERO, BigDecimal::add));
        cases.save(c);
        Map<String, Object> payload = new HashMap<>();
        payload.put("findingId", findingId.toString());
        payload.put("ruleId", f.getRuleId());
        payload.put("from", previous.name());
        payload.put("to", next.name());
        payload.put("reason", d.reason());
        payload.put("amount", f.getAmount());
        audit.record(caseId, user, "FINDING_" + action, payload);
        return detail(caseId);
    }

    @PreAuthorize("hasRole('REVIEWER')")
    @Transactional
    public CaseDetail decideCase(UUID caseId, Dtos.CaseDecision d, String user) {
        CaseEntity c = load(caseId);
        if (c.getCreatedBy().equals(user)) {
            throw ApiException.forbidden("Four-eyes rule: you uploaded this case, so another reviewer must decide it.");
        }
        requireReviewable(c);
        String action = d.action() == null ? "" : d.action().trim().toUpperCase();
        CaseStatus next = switch (action) {
            case "APPROVE" -> CaseStatus.APPROVED;
            case "REJECT" -> CaseStatus.REJECTED;
            case "ESCALATE" -> CaseStatus.ESCALATED;
            default -> throw ApiException.badRequest("action must be APPROVE, REJECT or ESCALATE.");
        };
        if (isBlank(d.reason())) {
            throw ApiException.badRequest("Give a reason for the decision. It goes into the audit trail.");
        }
        if (next == CaseStatus.ESCALATED && c.getStatus() == CaseStatus.ESCALATED) {
            throw ApiException.conflict("This case is already escalated.");
        }
        CaseStatus previous = c.getStatus();
        c.setStatus(next);
        cases.save(c);
        audit.record(caseId, user, "CASE_" + action,
                Map.of("from", previous.name(), "to", next.name(), "reason", d.reason()));
        return detail(caseId);
    }

    @PreAuthorize("hasRole('ANALYST')")
    public List<AuditView> audit(UUID caseId) {
        load(caseId);
        return audit.forCase(caseId).stream()
                .map(r -> new AuditView(r.id(), r.actor(), r.action(), r.payload(), r.hash(), r.createdAt()))
                .toList();
    }

    private CaseEntity load(UUID id) {
        return cases.findById(id).orElseThrow(() -> ApiException.notFound("Case " + id + " does not exist."));
    }

    private static void requireReviewable(CaseEntity c) {
        if (!REVIEWABLE.contains(c.getStatus())) {
            throw ApiException.conflict("Case is " + c.getStatus() + ". Decisions are possible once it is "
                    + "NEEDS_REVIEW, ESCALATED or AUTO_CLEARED.");
        }
    }

    private CaseSummary summary(CaseEntity c) {
        return new CaseSummary(c.getId(), c.getCaseType(), c.getTitle(), read(c.getAttributes()), c.getStatus(),
                c.getRiskScore(), c.getAmountAtRisk(), c.getCreatedBy(), c.getCreatedAt(), c.getUpdatedAt(),
                documents.countByCaseId(c.getId()), findings.countByCaseIdAndStatus(c.getId(), FindingStatus.OPEN));
    }

    private CaseDetail detail(UUID id) {
        CaseEntity c = load(id);
        List<DocumentView> docs = documents.findByCaseIdOrderByCreatedAt(id).stream().map(d -> new DocumentView(
                d.getId(), d.getFilename(), d.getMimeType(), d.getSha256(), d.getSizeBytes(), d.getPageCount(),
                extractions.findFirstByDocumentIdOrderByCreatedAtDesc(d.getId()).map(this::extractionSummary)
                        .orElse(null))).toList();
        List<FindingView> fs = findings.findByCaseIdOrderByWeightDescCreatedAtAsc(id).stream().map(f -> new FindingView(
                f.getId(), f.getRuleId(), f.getTitle(), f.getDetail(), f.getSeverity(), f.getWeight(), f.getAmount(),
                f.getSource(), read(f.getEvidence()), f.getLlmNote(), f.getVerified(), f.getStatus(), f.getDecidedBy(),
                f.getDecisionReason(), f.getDecidedAt(), f.getCreatedAt())).toList();
        CaseSummary sm = summary(c);
        List<Dtos.ExtractionRef> refs = docs.stream().filter(d -> d.extraction() != null)
                .map(d -> new Dtos.ExtractionRef(d.id(), d.extraction())).toList();
        return new CaseDetail(sm.id(), sm.caseType(), sm.title(), sm.attributes(), sm.status(), sm.riskScore(), sm.amountAtRisk(),
                sm.createdBy(), sm.createdAt(), sm.updatedAt(), sm.documentCount(), sm.openFindings(), docs, fs, refs);
    }

    static final int MAX_ATTRIBUTES_BYTES = 8192;

    /** Attributes are a flat-or-nested JSON object; anything else is rejected before a case exists. */
    JsonNode parseAttributes(String raw) {
        if (raw == null || raw.isBlank()) {
            return mapper.createObjectNode();
        }
        if (raw.getBytes(StandardCharsets.UTF_8).length > MAX_ATTRIBUTES_BYTES) {
            throw ApiException.badRequest("attributes is larger than " + MAX_ATTRIBUTES_BYTES + " bytes.");
        }
        JsonNode n;
        try {
            n = mapper.readTree(raw);
        } catch (JsonProcessingException e) {
            throw ApiException.badRequest("attributes must be valid JSON: " + e.getOriginalMessage());
        }
        if (n == null || !n.isObject()) {
            throw ApiException.badRequest("attributes must be a JSON object, e.g. {\"policyNo\": \"POL-1\"}.");
        }
        return n;
    }

    private ExtractionSummary extractionSummary(ExtractionEntity e) {
        JsonNode p = read(e.getPayload());
        return new ExtractionSummary(e.getModelProvider(), e.getModelName(), e.getPromptVersion(), e.getInputTokens(),
                e.getOutputTokens(), p.path("security"), p.path("fields"),
                p.hasNonNull("extraction_error") ? p.get("extraction_error").asText() : null);
    }

    private JsonNode read(String json) {
        try {
            return mapper.readTree(json);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
