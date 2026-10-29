package ai.caseintel.api.renewals;

import jakarta.persistence.LockModeType;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface CallRepository extends JpaRepository<CallEntity, UUID> {

    /** Row lock, so concurrent tool calls on one call cannot overwrite each other's counters or transcript. */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select c from CallEntity c where c.id = :id")
    Optional<CallEntity> findForUpdate(@Param("id") UUID id);
}
