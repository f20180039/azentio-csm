package ai.caseintel.api.renewals;

import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface CallRepository extends JpaRepository<CallEntity, UUID> {
}
