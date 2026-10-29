package ai.caseintel.api.audit;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class AuditChainTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final UUID CASE = UUID.randomUUID();

    private static List<AuditRow> chain(String... actions) throws Exception {
        List<AuditRow> rows = new ArrayList<>();
        String prev = AuditHasher.GENESIS;
        long id = 1;
        for (String action : actions) {
            JsonNode payload = MAPPER.readTree("{\"b\":2,\"a\":1.50}");
            Instant at = Instant.parse("2026-10-29T10:00:00.123456Z").plusSeconds(id);
            String hash = AuditHasher.hash(prev, "reviewer", action, payload, at);
            rows.add(new AuditRow(id++, CASE, "reviewer", action, payload, prev, hash, at));
            prev = hash;
        }
        return rows;
    }

    @Test
    void intactChainVerifies() throws Exception {
        var v = AuditChain.verify(chain("CASE_CREATED", "ROUTED", "CASE_APPROVE"));
        assertThat(v.valid()).isTrue();
        assertThat(v.checked()).isEqualTo(3);
        assertThat(v.brokenAt()).isNull();
    }

    @Test
    void editedPayloadIsDetectedAtThatEvent() throws Exception {
        List<AuditRow> rows = chain("CASE_CREATED", "ROUTED", "CASE_APPROVE");
        AuditRow r = rows.get(1);
        rows.set(1, new AuditRow(r.id(), r.caseId(), r.actor(), r.action(),
                MAPPER.readTree("{\"a\":1.5,\"b\":3}"), r.prevHash(), r.hash(), r.createdAt()));

        var v = AuditChain.verify(rows);
        assertThat(v.valid()).isFalse();
        assertThat(v.brokenAt()).isEqualTo(2L);
        assertThat(v.checked()).isEqualTo(1);
    }

    @Test
    void deletedEventBreaksTheNextLink() throws Exception {
        List<AuditRow> rows = chain("CASE_CREATED", "ROUTED", "CASE_APPROVE");
        rows.remove(1);
        var v = AuditChain.verify(rows);
        assertThat(v.valid()).isFalse();
        assertThat(v.brokenAt()).isEqualTo(3L);
    }

    @Test
    void hashIgnoresKeyOrderAndNumberSpelling() throws Exception {
        Instant at = Instant.parse("2026-10-29T10:00:00Z");
        String h1 = AuditHasher.hash(AuditHasher.GENESIS, "u", "A", MAPPER.readTree("{\"x\":1.50,\"y\":{\"q\":1,\"p\":2}}"), at);
        String h2 = AuditHasher.hash(AuditHasher.GENESIS, "u", "A", MAPPER.readTree("{\"y\":{\"p\":2,\"q\":1},\"x\":1.5}"), at);
        assertThat(h1).isEqualTo(h2).hasSize(64);
    }

    @Test
    void hashChangesWithActor() throws Exception {
        Instant at = Instant.parse("2026-10-29T10:00:00Z");
        JsonNode p = MAPPER.readTree("{}");
        assertThat(AuditHasher.hash(AuditHasher.GENESIS, "a", "X", p, at))
                .isNotEqualTo(AuditHasher.hash(AuditHasher.GENESIS, "b", "X", p, at));
    }
}
