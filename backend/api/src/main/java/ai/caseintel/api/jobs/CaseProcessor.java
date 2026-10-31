package ai.caseintel.api.jobs;

import ai.caseintel.api.agent.AgentClient;
import ai.caseintel.api.agent.AgentException;
import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.domain.CaseEntity;
import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.domain.DocumentEntity;
import ai.caseintel.api.domain.ExtractionEntity;
import ai.caseintel.api.domain.FindingEntity;
import ai.caseintel.api.domain.FindingSource;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.repo.DocumentRepository;
import ai.caseintel.api.repo.ExtractionRepository;
import ai.caseintel.api.repo.FindingRepository;
import ai.caseintel.api.repo.PeerQueries;
import ai.caseintel.api.rules.FindingDraft;
import ai.caseintel.api.rules.PackRegistry;
import ai.caseintel.api.rules.Rule;
import ai.caseintel.api.rules.RuleContext;
import ai.caseintel.api.rules.Scoring;
import ai.caseintel.api.service.ProcessingMetrics;
import ai.caseintel.api.storage.FileStorage;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.NullNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

/** One case through extract → rules → score → explain → route. Agent calls run outside DB transactions. */
@Component
public class CaseProcessor {

    private static final Set<CaseStatus> PROCESSABLE = Set.of(CaseStatus.RECEIVED, CaseStatus.PROCESSING);

    private final CaseRepository cases;
    private final DocumentRepository documents;
    private final ExtractionRepository extractions;
    private final FindingRepository findings;
    private final PeerQueries peers;
    private final PackRegistry packs;
    private final AgentClient agent;
    private final FileStorage storage;
    private final AuditService audit;
    private final ProcessingMetrics metrics;
    private final ObjectMapper mapper;
    private final TransactionTemplate tx;

    public CaseProcessor(CaseRepository cases, DocumentRepository documents, ExtractionRepository extractions,
                         FindingRepository findings, PeerQueries peers, PackRegistry packs, AgentClient agent, FileStorage storage,
                         AuditService audit, ProcessingMetrics metrics, ObjectMapper mapper, TransactionTemplate tx) {
        this.cases = cases;
        this.documents = documents;
        this.extractions = extractions;
        this.findings = findings;
        this.peers = peers;
        this.packs = packs;
        this.agent = agent;
        this.storage = storage;
        this.audit = audit;
        this.metrics = metrics;
        this.mapper = mapper;
        this.tx = tx;
    }

    public void process(UUID caseId, int attempt, boolean lastAttempt) {
        CaseEntity c = cases.findById(caseId).orElseThrow(() -> new IllegalStateException("Case " + caseId + " is gone"));
        if (!PROCESSABLE.contains(c.getStatus())) {
            return;
        }
        PackRegistry.Pack pack = packs.find(c.getCaseType())
                .orElseThrow(() -> new IllegalStateException("No rule pack for " + c.getCaseType()));

        tx.executeWithoutResult(s -> {
            c.setStatus(CaseStatus.PROCESSING);
            cases.save(c);
            audit.record(caseId, "system", "PROCESSING_STARTED", Map.of("attempt", attempt));
        });

        List<DocumentEntity> docs = documents.findByCaseIdOrderByCreatedAt(caseId);
        Map<UUID, JsonNode> extracted = new LinkedHashMap<>();
        for (DocumentEntity doc : docs) {
            extracted.put(doc.getId(), extract(doc, pack.code().extractionSchema()));
        }

        RuleContext ctx = new RuleContext(c, docs, extracted, pack.config(),
                d -> documents.findOtherCaseIdsWithSha(d.getSha256(), caseId), peers.forCase(c));
        List<FindingEntity> drafted = new ArrayList<>();
        Instant now = Instant.now();
        for (Rule rule : pack.rules()) {
            double weight = pack.config().rules().get(rule.id()).weight();
            for (FindingDraft d : rule.evaluate(ctx)) {
                drafted.add(new FindingEntity(UUID.randomUUID(), caseId, d.ruleId(), d.title(), d.detail(),
                        d.severity(), BigDecimal.valueOf(weight), d.amount(), d.source(), json(d.evidence()), now));
            }
        }

        explain(c, drafted, extracted, lastAttempt);

        List<Scoring.Weighted> weighted = drafted.stream()
                .map(f -> new Scoring.Weighted(f.getWeight().doubleValue(), f.getSeverity(), f.getSource()))
                .toList();
        BigDecimal score = Scoring.score(weighted);
        CaseStatus status = Scoring.route(score, pack.config().routing(), weighted);
        BigDecimal atRisk = drafted.stream().map(FindingEntity::getAmount).filter(Objects::nonNull)
                .reduce(BigDecimal.ZERO, BigDecimal::add);

        tx.executeWithoutResult(s -> {
            findings.deleteOpenByCaseId(caseId);
            findings.saveAll(drafted);
            c.setRiskScore(score);
            c.setAmountAtRisk(atRisk);
            c.setStatus(status);
            cases.save(c);
            audit.record(caseId, "system", "ROUTED", Map.of(
                    "score", score,
                    "status", status.name(),
                    "amountAtRisk", atRisk,
                    "findings", drafted.stream().map(FindingEntity::getRuleId).toList(),
                    "routing", pack.config().routing()));
        });
        metrics.recordProcessing(Duration.between(c.getCreatedAt(), Instant.now()).toMillis());
    }

    private JsonNode extract(DocumentEntity doc, String schema) {
        var existing = extractions.findFirstByDocumentIdOrderByCreatedAtDesc(doc.getId());
        if (existing.isPresent()) {
            return read(existing.get().getPayload());
        }
        JsonNode res = agent.extract(storage.resolve(doc.getStoragePath()), doc.getFilename(), schema);
        JsonNode model = res.path("model");
        JsonNode usage = res.path("usage");
        tx.executeWithoutResult(s -> {
            extractions.save(new ExtractionEntity(UUID.randomUUID(), doc.getId(), json(res),
                    model.path("provider").asText(null), model.path("name").asText(null),
                    model.path("prompt_version").asText(null),
                    usage.path("input_tokens").isNumber() ? usage.path("input_tokens").asInt() : null,
                    usage.path("output_tokens").isNumber() ? usage.path("output_tokens").asInt() : null,
                    Instant.now()));
            if (res.path("page_count").isNumber()) {
                doc.setPageCount(res.path("page_count").asInt());
                documents.save(doc);
            }
            Map<String, Object> payload = new HashMap<>();
            payload.put("documentId", doc.getId().toString());
            payload.put("model", present(model));
            payload.put("usage", present(usage));
            payload.put("hiddenSpans", res.path("security").path("hidden_text").size());
            payload.put("injectionSuspected", res.path("security").path("injection").path("suspected").asBoolean(false));
            payload.put("piiMasked", present(res.path("security").path("pii").path("masked")));
            audit.record(doc.getCaseId(), "system", "EXTRACTED", payload);
        });
        return res;
    }

    /**
     * Asks the model to explain rule findings. Security findings are never sent: their evidence is the hostile
     * text itself. On the last attempt an agent failure is tolerated, since the deterministic findings stand alone.
     */
    private void explain(CaseEntity c, List<FindingEntity> drafted, Map<UUID, JsonNode> extracted, boolean lastAttempt) {
        List<FindingEntity> explainable = drafted.stream().filter(f -> f.getSource() != FindingSource.SECURITY).toList();
        if (explainable.isEmpty()) {
            return;
        }
        ObjectNode req = mapper.createObjectNode();
        req.put("case_type", c.getCaseType());
        ArrayNode fs = req.putArray("findings");
        for (FindingEntity f : explainable) {
            ObjectNode n = fs.addObject();
            n.put("id", f.getId().toString());
            n.put("rule_id", f.getRuleId());
            n.put("title", f.getTitle());
            n.put("detail", f.getDetail());
            n.set("evidence", read(f.getEvidence()));
        }
        ArrayNode pages = req.putArray("pages");
        extracted.forEach((docId, ex) -> ex.path("pages").forEach(p -> {
            ObjectNode n = pages.addObject();
            n.put("document_id", docId.toString());
            n.put("page", p.path("page").asInt());
            n.put("text", p.path("text").asText());
        }));

        JsonNode res;
        try {
            res = agent.explain(req);
        } catch (AgentException e) {
            if (!lastAttempt) {
                throw e;
            }
            audit.record(c.getId(), "system", "EXPLAIN_SKIPPED", Map.of("error", e.getMessage()));
            return;
        }
        Map<String, FindingEntity> byId = new HashMap<>();
        explainable.forEach(f -> byId.put(f.getId().toString(), f));
        for (JsonNode note : res.path("notes")) {
            FindingEntity f = byId.get(note.path("finding_id").asText());
            if (f != null) {
                f.explain(note.path("note").asText(), true);
            }
        }
        for (JsonNode d : res.path("dropped")) {
            FindingEntity f = byId.get(d.path("finding_id").asText());
            if (f != null && f.getLlmNote() == null) {
                f.explain(null, false);
            }
        }
        audit.record(c.getId(), "system", "EXPLAINED", Map.of(
                "model", present(res.path("model")),
                "usage", present(res.path("usage")),
                "notes", res.path("notes").size(),
                "dropped", present(res.path("dropped"))));
    }

    private static JsonNode present(JsonNode n) {
        return n.isMissingNode() ? NullNode.getInstance() : n;
    }

    private String json(Object o) {
        try {
            return mapper.writeValueAsString(o);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    private JsonNode read(String s) {
        try {
            return mapper.readTree(s);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }
}
