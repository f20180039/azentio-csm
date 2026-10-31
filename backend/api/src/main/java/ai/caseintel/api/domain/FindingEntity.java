package ai.caseintel.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "findings")
public class FindingEntity {

    @Id
    private UUID id;

    @Column(name = "case_id", nullable = false)
    private UUID caseId;

    @Column(name = "rule_id", nullable = false)
    private String ruleId;

    @Column(nullable = false)
    private String title;

    private String detail;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private Severity severity;

    @Column(nullable = false, precision = 5, scale = 3)
    private BigDecimal weight;

    @Column(precision = 14, scale = 2)
    private BigDecimal amount;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private FindingSource source;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private String evidence;

    @Column(name = "llm_note")
    private String llmNote;

    private Boolean verified;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private FindingStatus status;

    @Column(name = "decided_by")
    private String decidedBy;

    @Column(name = "decision_reason")
    private String decisionReason;

    @Column(name = "decided_at")
    private Instant decidedAt;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected FindingEntity() {}

    public FindingEntity(UUID id, UUID caseId, String ruleId, String title, String detail, Severity severity,
                         BigDecimal weight, BigDecimal amount, FindingSource source, String evidence, Instant createdAt) {
        this.id = id;
        this.caseId = caseId;
        this.ruleId = ruleId;
        this.title = title;
        this.detail = detail;
        this.severity = severity;
        this.weight = weight;
        this.amount = amount;
        this.source = source;
        this.evidence = evidence;
        this.status = FindingStatus.OPEN;
        this.createdAt = createdAt;
    }

    public UUID getId() { return id; }
    public UUID getCaseId() { return caseId; }
    public String getRuleId() { return ruleId; }
    public String getTitle() { return title; }
    public String getDetail() { return detail; }
    public Severity getSeverity() { return severity; }
    public BigDecimal getWeight() { return weight; }
    public BigDecimal getAmount() { return amount; }
    public FindingSource getSource() { return source; }
    public String getEvidence() { return evidence; }
    public String getLlmNote() { return llmNote; }
    public Boolean getVerified() { return verified; }
    public FindingStatus getStatus() { return status; }
    public String getDecidedBy() { return decidedBy; }
    public String getDecisionReason() { return decisionReason; }
    public Instant getDecidedAt() { return decidedAt; }
    public Instant getCreatedAt() { return createdAt; }

    public void explain(String note, boolean verified) {
        this.llmNote = note;
        this.verified = verified;
    }

    public void decide(FindingStatus status, String by, String reason, BigDecimal amount) {
        this.status = status;
        this.decidedBy = by;
        this.decisionReason = reason;
        this.decidedAt = Instant.now();
        if (amount != null) {
            this.amount = amount;
        }
    }
}
