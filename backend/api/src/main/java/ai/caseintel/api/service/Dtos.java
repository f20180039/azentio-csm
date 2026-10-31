package ai.caseintel.api.service;

import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.domain.FindingSource;
import ai.caseintel.api.domain.FindingStatus;
import ai.caseintel.api.domain.Severity;
import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public final class Dtos {

    private Dtos() {}

    public record CaseSummary(UUID id, String caseType, String title, JsonNode attributes, CaseStatus status,
                              BigDecimal riskScore, BigDecimal amountAtRisk, String createdBy, Instant createdAt, Instant updatedAt,
                              long documentCount, long openFindings) {}

    public record ExtractionSummary(String modelProvider, String modelName, String promptVersion,
                                    Integer inputTokens, Integer outputTokens, JsonNode security, JsonNode fields,
                                    String extractionError) {}

    public record DocumentView(UUID id, String filename, String mimeType, String sha256, long sizeBytes,
                               Integer pageCount, ExtractionSummary extraction) {}

    public record FindingView(UUID id, String ruleId, String title, String detail, Severity severity,
                              BigDecimal weight, BigDecimal amount, FindingSource source, JsonNode evidence,
                              String llmNote, Boolean verified, FindingStatus status, String decidedBy,
                              String decisionReason, Instant decidedAt, Instant createdAt) {}

    public record ExtractionRef(UUID documentId, ExtractionSummary extraction) {}

    /** Case fields at top level so the web app reads one flat object. */
    public record CaseDetail(UUID id, String caseType, String title, JsonNode attributes, CaseStatus status,
                             BigDecimal riskScore, BigDecimal amountAtRisk, String createdBy, Instant createdAt, Instant updatedAt,
                             long documentCount, long openFindings, List<DocumentView> documents,
                             List<FindingView> findings, List<ExtractionRef> extractions) {}

    public record UploadResult(CaseDetail detail, boolean cacheHit) {}

    public record PageView(int page, String text) {}

    public record FindingDecision(String action, String reason, BigDecimal amount) {}

    public record CaseDecision(String action, String reason) {}

    public record AuditView(long id, String actor, String action, JsonNode payload, String hash, Instant createdAt) {}

    public record RuleView(String id, boolean core, double weight, String rationale, JsonNode params) {}

    public record PackView(String caseType, String label, String extractionSchema, double autoClearBelow,
                           double escalateAtOrAbove, List<RuleView> rules) {}

    public record Stats(Map<String, Long> byStatus, long jobsPending, Long p50Ms, Long p95Ms, int samples,
                        long cacheHits, long cacheMisses) {}

    public record Me(String username, List<String> roles) {}

    public record Health(String status, String db, String agent) {}
}
