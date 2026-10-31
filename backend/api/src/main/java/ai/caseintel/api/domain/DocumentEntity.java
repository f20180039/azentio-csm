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
@Table(name = "documents")
public class DocumentEntity {

    @Id
    private UUID id;

    @Column(name = "case_id", nullable = false)
    private UUID caseId;

    @Column(nullable = false)
    private String filename;

    @Column(name = "mime_type")
    private String mimeType;

    @JdbcTypeCode(SqlTypes.CHAR)
    @Column(nullable = false, columnDefinition = "char(64)")
    private String sha256;

    @Column(name = "size_bytes", nullable = false)
    private long sizeBytes;

    @Column(name = "storage_path", nullable = false)
    private String storagePath;

    @Column(name = "page_count")
    private Integer pageCount;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    protected DocumentEntity() {}

    public DocumentEntity(UUID id, UUID caseId, String filename, String mimeType, String sha256, long sizeBytes,
                          String storagePath, Integer pageCount, Instant createdAt) {
        this.id = id;
        this.caseId = caseId;
        this.filename = filename;
        this.mimeType = mimeType;
        this.sha256 = sha256;
        this.sizeBytes = sizeBytes;
        this.storagePath = storagePath;
        this.pageCount = pageCount;
        this.createdAt = createdAt;
    }

    public UUID getId() { return id; }
    public UUID getCaseId() { return caseId; }
    public String getFilename() { return filename; }
    public String getMimeType() { return mimeType; }
    public String getSha256() { return sha256; }
    public long getSizeBytes() { return sizeBytes; }
    public String getStoragePath() { return storagePath; }
    public Integer getPageCount() { return pageCount; }
    public Instant getCreatedAt() { return createdAt; }

    public void setPageCount(Integer pageCount) { this.pageCount = pageCount; }
}
