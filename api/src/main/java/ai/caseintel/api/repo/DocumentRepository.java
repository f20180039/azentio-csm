package ai.caseintel.api.repo;

import ai.caseintel.api.domain.DocumentEntity;
import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface DocumentRepository extends JpaRepository<DocumentEntity, UUID> {

    List<DocumentEntity> findByCaseIdOrderByCreatedAt(UUID caseId);

    @Query("select distinct d.caseId from DocumentEntity d where d.sha256 = :sha and d.caseId <> :caseId")
    List<UUID> findOtherCaseIdsWithSha(@Param("sha") String sha256, @Param("caseId") UUID caseId);

    @Query("""
            select distinct d.caseId from DocumentEntity d, CaseEntity c
            where d.caseId = c.id and d.sha256 = :sha and c.caseType = :caseType and c.pipelineVersion = :version
            """)
    List<UUID> findCaseIdsWithSha(@Param("sha") String sha256, @Param("caseType") String caseType,
                                  @Param("version") String pipelineVersion);

    long countByCaseId(UUID caseId);
}
