package ai.caseintel.api.repo;

import ai.caseintel.api.domain.CaseEntity;
import ai.caseintel.api.domain.DocumentEntity;
import ai.caseintel.api.rules.Peers;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.Timestamp;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Supplier;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/** Builds a {@link Peers} view for one case. Plain JDBC so the jsonb containment query uses its GIN index. */
@Component
public class PeerQueries {

    private static final String SELECT = """
            SELECT id, title, attributes::text AS attributes, status, risk_score, created_at
            FROM cases WHERE case_type = ? AND id <> ? AND created_at >= ?""";

    private final JdbcTemplate jdbc;
    private final DocumentRepository documents;
    private final ExtractionRepository extractions;
    private final ObjectMapper mapper;

    public PeerQueries(JdbcTemplate jdbc, DocumentRepository documents, ExtractionRepository extractions,
                       ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.documents = documents;
        this.extractions = extractions;
        this.mapper = mapper;
    }

    public Peers forCase(CaseEntity c) {
        return new Peers() {
            @Override
            public List<Peer> recent(Duration window, int limit) {
                return jdbc.query(SELECT + " ORDER BY created_at DESC LIMIT ?", (rs, i) -> peer(rs),
                        c.getCaseType(), c.getId(), since(c, window), Math.min(Math.max(limit, 0), MAX_PEERS));
            }

            @Override
            public List<Peer> withAttribute(String key, String value, Duration window) {
                String probe = mapper.createObjectNode().put(key, value).toString();
                return jdbc.query(SELECT + " AND attributes @> ?::jsonb ORDER BY created_at DESC LIMIT ?",
                        (rs, i) -> peer(rs), c.getCaseType(), c.getId(), since(c, window), probe, MAX_PEERS);
            }
        };
    }

    /** The window counts back from the case's own creation, so reprocessing an old case sees the same peers. */
    private static Timestamp since(CaseEntity c, Duration window) {
        return Timestamp.from(c.getCreatedAt().minus(window));
    }

    private Peers.Peer peer(java.sql.ResultSet rs) throws java.sql.SQLException {
        UUID id = rs.getObject("id", UUID.class);
        return new Peers.Peer(id, rs.getString("title"), read(rs.getString("attributes")), rs.getString("status"),
                rs.getBigDecimal("risk_score"), rs.getTimestamp("created_at").toInstant(), memo(() -> extractionsOf(id)));
    }

    private Map<UUID, JsonNode> extractionsOf(UUID caseId) {
        Map<UUID, JsonNode> out = new LinkedHashMap<>();
        for (DocumentEntity d : documents.findByCaseIdOrderByCreatedAt(caseId)) {
            extractions.findFirstByDocumentIdOrderByCreatedAtDesc(d.getId())
                    .ifPresent(e -> out.put(d.getId(), read(e.getPayload())));
        }
        return out;
    }

    private static <T> Supplier<T> memo(Supplier<T> s) {
        return new Supplier<>() {
            private T value;

            @Override
            public synchronized T get() {
                if (value == null) {
                    value = s.get();
                }
                return value;
            }
        };
    }

    private JsonNode read(String json) {
        try {
            return mapper.readTree(json);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }
}
