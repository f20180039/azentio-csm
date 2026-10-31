package ai.caseintel.api.rules;

import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Supplier;

/**
 * Other cases of the same type, for population rules: linked applications, provider outliers, overlapping claims.
 * The current case is never returned. Extractions load only when a rule asks for them.
 */
public interface Peers {

    int MAX_PEERS = 500;

    /** Most recent first, created within {@code window}, at most {@code limit} (capped at {@link #MAX_PEERS}). */
    List<Peer> recent(Duration window, int limit);

    /** Cases whose attributes hold {@code key = value}, created within {@code window}, most recent first. */
    List<Peer> withAttribute(String key, String value, Duration window);

    Peers NONE = new Peers() {
        @Override
        public List<Peer> recent(Duration window, int limit) {
            return List.of();
        }

        @Override
        public List<Peer> withAttribute(String key, String value, Duration window) {
            return List.of();
        }
    };

    record Peer(UUID id, String title, JsonNode attributes, String status, BigDecimal riskScore, Instant createdAt,
                Supplier<Map<UUID, JsonNode>> extractions) {}
}
