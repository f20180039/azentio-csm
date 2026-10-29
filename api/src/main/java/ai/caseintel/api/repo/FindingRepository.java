package ai.caseintel.api.repo;

import ai.caseintel.api.domain.FindingEntity;
import ai.caseintel.api.domain.FindingStatus;
import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface FindingRepository extends JpaRepository<FindingEntity, UUID> {

    List<FindingEntity> findByCaseIdOrderByWeightDescCreatedAtAsc(UUID caseId);

    long countByCaseIdAndStatus(UUID caseId, FindingStatus status);

    @Modifying
    @Query("delete from FindingEntity f where f.caseId = :caseId and f.status = ai.caseintel.api.domain.FindingStatus.OPEN")
    int deleteOpenByCaseId(@Param("caseId") UUID caseId);
}
