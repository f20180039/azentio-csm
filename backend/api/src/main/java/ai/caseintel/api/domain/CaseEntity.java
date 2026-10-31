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
@Table(name = "cases")
public class CaseEntity {

    @Id
    private UUID id;

    @Column(name = "case_type", nullable = false)
    private String caseType;

    @Column(nullable = false)
    private String title;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private CaseStatus status;

    @Column(name = "risk_score", precision = 4, scale = 3)
    private BigDecimal riskScore;

    @Column(name = "amount_at_risk", precision = 14, scale = 2)
    private BigDecimal amountAtRisk;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private String attributes = "{}";

    @Column(name = "pipeline_version", nullable = false)
    private String pipelineVersion;

    @Column(name = "created_by", nullable = false)
    private String createdBy;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected CaseEntity() {}

    public CaseEntity(UUID id, String caseType, String title, String pipelineVersion, String createdBy, Instant now) {
        this.id = id;
        this.caseType = caseType;
        this.title = title;
        this.status = CaseStatus.RECEIVED;
        this.pipelineVersion = pipelineVersion;
        this.createdBy = createdBy;
        this.createdAt = now;
        this.updatedAt = now;
    }

    public CaseEntity(UUID id, String caseType, String title, String attributes, String pipelineVersion,
                      String createdBy, Instant now) {
        this(id, caseType, title, pipelineVersion, createdBy, now);
        this.attributes = attributes;
    }

    public UUID getId() { return id; }
    public String getCaseType() { return caseType; }
    public String getTitle() { return title; }
    public CaseStatus getStatus() { return status; }
    public BigDecimal getRiskScore() { return riskScore; }
    public BigDecimal getAmountAtRisk() { return amountAtRisk; }
    public String getAttributes() { return attributes; }
    public String getPipelineVersion() { return pipelineVersion; }
    public String getCreatedBy() { return createdBy; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getUpdatedAt() { return updatedAt; }

    public void setStatus(CaseStatus status) {
        this.status = status;
        this.updatedAt = Instant.now();
    }

    public void setRiskScore(BigDecimal riskScore) { this.riskScore = riskScore; }
    public void setAmountAtRisk(BigDecimal amountAtRisk) { this.amountAtRisk = amountAtRisk; }
}
