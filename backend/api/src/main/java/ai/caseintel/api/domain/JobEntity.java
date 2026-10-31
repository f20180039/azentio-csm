package ai.caseintel.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "jobs")
public class JobEntity {

    @Id
    private UUID id;

    @Column(name = "case_id", nullable = false)
    private UUID caseId;

    @Column(nullable = false)
    private String kind;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private JobStatus status;

    @Column(nullable = false)
    private int attempts;

    @Column(name = "run_after", nullable = false)
    private Instant runAfter;

    @Column(name = "last_error")
    private String lastError;

    @Column(name = "idempotency_key", unique = true)
    private String idempotencyKey;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected JobEntity() {}

    public JobEntity(UUID id, UUID caseId, String kind, String idempotencyKey, Instant now) {
        this.id = id;
        this.caseId = caseId;
        this.kind = kind;
        this.status = JobStatus.PENDING;
        this.idempotencyKey = idempotencyKey;
        this.runAfter = now;
        this.createdAt = now;
        this.updatedAt = now;
    }

    public UUID getId() { return id; }
    public UUID getCaseId() { return caseId; }
    public String getKind() { return kind; }
    public JobStatus getStatus() { return status; }
    public int getAttempts() { return attempts; }
    public Instant getRunAfter() { return runAfter; }
    public String getLastError() { return lastError; }
    public String getIdempotencyKey() { return idempotencyKey; }
}
