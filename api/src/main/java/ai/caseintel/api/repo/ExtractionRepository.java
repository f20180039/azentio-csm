package ai.caseintel.api.repo;

import ai.caseintel.api.domain.ExtractionEntity;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ExtractionRepository extends JpaRepository<ExtractionEntity, UUID> {

    Optional<ExtractionEntity> findFirstByDocumentIdOrderByCreatedAtDesc(UUID documentId);
}
