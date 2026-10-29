package ai.caseintel.api.audit;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Instant;
import java.util.UUID;

public record AuditRow(long id, UUID caseId, String actor, String action, JsonNode payload, String prevHash,
                       String hash, Instant createdAt) {}
