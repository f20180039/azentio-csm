package ai.caseintel.api.repo;

import ai.caseintel.api.domain.JobEntity;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface JobRepository extends JpaRepository<JobEntity, UUID> {
}
