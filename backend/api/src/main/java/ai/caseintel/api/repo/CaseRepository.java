package ai.caseintel.api.repo;

import ai.caseintel.api.domain.CaseEntity;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;

public interface CaseRepository extends JpaRepository<CaseEntity, UUID>, JpaSpecificationExecutor<CaseEntity> {
}
