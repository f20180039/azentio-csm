package ai.caseintel.api.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

@Entity
@Table(name = "extractions")
public class ExtractionEntity {

    @Id
    private UUID id;

    @Column(name = "document_id", nullable = false)
    private UUID documentId;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(nullable = false, columnDefinition = "jsonb")
    private String payload;

    @Column(name = "model_provider")
    private String modelProvider;

    @Column(name = "model_name")
    private String modelName;

    @Column(name = "prompt_version")
    private String promptVersion;

    @Column(name = "input_tokens")
    private Integer inputTokens;

    @Column(name = "output_tokens")
    private Integer outputTokens;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected ExtractionEntity() {}

    public ExtractionEntity(UUID id, UUID documentId, String payload, String modelProvider, String modelName,
                            String promptVersion, Integer inputTokens, Integer outputTokens, Instant createdAt) {
        this.id = id;
        this.documentId = documentId;
        this.payload = payload;
        this.modelProvider = modelProvider;
        this.modelName = modelName;
        this.promptVersion = promptVersion;
        this.inputTokens = inputTokens;
        this.outputTokens = outputTokens;
        this.createdAt = createdAt;
    }

    public UUID getId() { return id; }
    public UUID getDocumentId() { return documentId; }
    public String getPayload() { return payload; }
    public String getModelProvider() { return modelProvider; }
    public String getModelName() { return modelName; }
    public String getPromptVersion() { return promptVersion; }
    public Integer getInputTokens() { return inputTokens; }
    public Integer getOutputTokens() { return outputTokens; }
    public Instant getCreatedAt() { return createdAt; }
}
