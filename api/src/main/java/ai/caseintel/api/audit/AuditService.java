package ai.caseintel.api.audit;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuditService {

    // Arbitrary key for pg_advisory_xact_lock; serialises appends so the chain never forks.
    private static final long CHAIN_LOCK = 0x4155444954L;

    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public AuditService(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    @Transactional
    public void record(UUID caseId, String actor, String action, Object payload) {
        JsonNode node = mapper.valueToTree(payload == null ? java.util.Map.of() : payload);
        jdbc.queryForObject("select pg_advisory_xact_lock(?)", Object.class, CHAIN_LOCK);
        List<String> last = jdbc.queryForList("select hash from audit_events order by id desc limit 1", String.class);
        String prev = last.isEmpty() ? AuditHasher.GENESIS : last.get(0);
        // Postgres keeps microseconds; truncating here makes the stored value hash the same on read-back.
        Instant now = Instant.now().truncatedTo(ChronoUnit.MICROS);
        String hash = AuditHasher.hash(prev, actor, action, node, now);
        jdbc.update("""
                insert into audit_events(case_id, actor, action, payload, prev_hash, hash, created_at)
                values (?, ?, ?, ?::jsonb, ?, ?, ?)
                """, caseId, actor, action, toJson(node), prev, hash, Timestamp.from(now));
    }

    public List<AuditRow> forCase(UUID caseId) {
        return jdbc.query("select * from audit_events where case_id = ? order by id", this::map, caseId);
    }

    @Transactional(readOnly = true)
    public AuditChain.Verification verifyAll() {
        return AuditChain.verify(jdbc.query("select * from audit_events order by id", this::map));
    }

    private AuditRow map(ResultSet rs, int i) throws SQLException {
        try {
            return new AuditRow(
                    rs.getLong("id"),
                    rs.getObject("case_id", UUID.class),
                    rs.getString("actor"),
                    rs.getString("action"),
                    mapper.readTree(rs.getString("payload")),
                    rs.getString("prev_hash"),
                    rs.getString("hash"),
                    rs.getTimestamp("created_at").toInstant());
        } catch (JsonProcessingException e) {
            throw new SQLException("Bad audit payload in event " + rs.getLong("id"), e);
        }
    }

    private String toJson(JsonNode node) {
        try {
            return mapper.writeValueAsString(node);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }
}
