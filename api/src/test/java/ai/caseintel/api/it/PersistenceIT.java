package ai.caseintel.api.it;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.domain.CaseEntity;
import ai.caseintel.api.jobs.JobQueue;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.repo.PeerQueries;
import ai.caseintel.api.rules.Peers;
import ai.caseintel.api.service.OpsService;
import java.time.Duration;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.test.context.support.WithMockUser;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * Runs against Postgres: a Testcontainers instance by default, or an existing empty database when
 * IT_DB_URL / IT_DB_USER / IT_DB_PASSWORD are set (useful without Docker).
 */
@Tag("integration")
@SpringBootTest(properties = {"app.worker.enabled=false", "app.agent.base-url=http://127.0.0.1:9"})
class PersistenceIT {

    private static PostgreSQLContainer<?> pg;

    @DynamicPropertySource
    static void db(DynamicPropertyRegistry r) {
        String url = System.getenv("IT_DB_URL");
        if (url != null) {
            r.add("spring.datasource.url", () -> url);
            r.add("spring.datasource.username", () -> System.getenv().getOrDefault("IT_DB_USER", "postgres"));
            r.add("spring.datasource.password", () -> System.getenv().getOrDefault("IT_DB_PASSWORD", ""));
            return;
        }
        pg = new PostgreSQLContainer<>("postgres:16-alpine");
        pg.start();
        r.add("spring.datasource.url", pg::getJdbcUrl);
        r.add("spring.datasource.username", pg::getUsername);
        r.add("spring.datasource.password", pg::getPassword);
    }

    @Autowired
    JdbcTemplate jdbc;
    @Autowired
    AuditService audit;
    @Autowired
    OpsService ops;
    @Autowired
    JobQueue queue;
    @Autowired
    PeerQueries peerQueries;
    @Autowired
    CaseRepository cases;

    @Test
    @WithMockUser(roles = "ADMIN")
    void auditChainIsAppendOnlyAndVerifies() {
        UUID caseId = UUID.randomUUID();
        audit.record(caseId, "it", "FIRST", Map.of("amount", 1.50, "z", "a"));
        audit.record(caseId, "it", "SECOND", Map.of("n", 10_000_000_000L));

        assertThat(ops.verifyAudit().valid()).isTrue();
        assertThatThrownBy(() -> jdbc.update("update audit_events set actor = 'mallory'"))
                .hasMessageContaining("append-only");
        assertThatThrownBy(() -> jdbc.update("delete from audit_events"))
                .hasMessageContaining("append-only");
    }

    @Test
    void queueClaimsEachJobOnceAndHonoursIdempotencyKey() {
        UUID caseId = UUID.randomUUID();
        jdbc.update("""
                insert into cases(id, case_type, title, status, pipeline_version, created_by)
                values (?, 'demo', 't', 'RECEIVED', 'v1', 'it')
                """, caseId);
        queue.enqueue(caseId, JobQueue.PROCESS_CASE, caseId + ":process:v1");
        queue.enqueue(caseId, JobQueue.PROCESS_CASE, caseId + ":process:v1");

        JobQueue.ClaimedJob first = queue.claim();
        assertThat(first).isNotNull();
        assertThat(first.caseId()).isEqualTo(caseId);
        assertThat(first.attempts()).isEqualTo(1);
        assertThat(queue.claim()).isNull();

        queue.complete(first.id());
        assertThat(jdbc.queryForObject("select status from jobs where id = ?", String.class, first.id()))
                .isEqualTo("DONE");
    }

    @Test
    void peersAreSameTypeWithinWindowAndMatchOnAttributes() {
        String type = "peer-" + UUID.randomUUID();
        Instant now = Instant.now().truncatedTo(ChronoUnit.MILLIS);
        CaseEntity self = cases.saveAndFlush(new CaseEntity(UUID.randomUUID(), type, "self",
                "{\"payerHash\":\"p1\"}", "v1", "it", now));
        UUID sharesPayer = insertCase(type, "{\"payerHash\":\"p1\",\"agent\":\"a9\"}", now.minus(Duration.ofDays(10)));
        UUID otherPayer = insertCase(type, "{\"payerHash\":\"p2\"}", now.minus(Duration.ofDays(1)));
        insertCase(type, "{\"payerHash\":\"p1\"}", now.minus(Duration.ofDays(120)));
        insertCase("other-" + type, "{\"payerHash\":\"p1\"}", now.minus(Duration.ofDays(1)));

        Peers peers = peerQueries.forCase(self);

        assertThat(peers.recent(Duration.ofDays(90), 10)).extracting(Peers.Peer::id)
                .containsExactly(otherPayer, sharesPayer);
        assertThat(peers.recent(Duration.ofDays(90), 1)).hasSize(1);
        assertThat(peers.withAttribute("payerHash", "p1", Duration.ofDays(90))).singleElement()
                .satisfies(p -> {
                    assertThat(p.id()).isEqualTo(sharesPayer);
                    assertThat(p.attributes().path("agent").asText()).isEqualTo("a9");
                    assertThat(p.extractions().get()).isEmpty();
                });
        assertThat(peers.withAttribute("payerHash", "p1\" or 1=1", Duration.ofDays(90))).isEmpty();
    }

    private UUID insertCase(String type, String attributes, Instant createdAt) {
        UUID id = UUID.randomUUID();
        jdbc.update("""
                insert into cases(id, case_type, title, attributes, status, pipeline_version, created_by, created_at)
                values (?, ?, 't', ?::jsonb, 'NEEDS_REVIEW', 'v1', 'it', ?)
                """, id, type, attributes, java.sql.Timestamp.from(createdAt));
        return id;
    }
}
