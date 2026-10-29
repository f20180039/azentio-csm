package ai.caseintel.api.renewals;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import ai.caseintel.api.renewals.RenewalDtos.Dashboard;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * The dashboard is SQL, so it runs against real Postgres: each test gets a fresh schema with the real
 * migrations (IT_DB_URL / IT_DB_USER / IT_DB_PASSWORD point at an existing database, else Testcontainers).
 */
@Tag("integration")
class DashboardServiceTest {

    private static final ZoneId IST = ZoneId.of("Asia/Kolkata");
    private static final Clock CLOCK = Clock.fixed(
            LocalDateTime.parse("2026-10-29T10:00:00").atZone(IST).toInstant(), IST);
    private static final LocalDate TODAY = LocalDate.of(2026, 10, 29);

    private static PostgreSQLContainer<?> pg;

    private String schema;
    private JdbcTemplate jdbc;
    private final PolicyRepository policies = mock(PolicyRepository.class);

    private static synchronized String[] connection() {
        String url = System.getenv("IT_DB_URL");
        if (url != null) {
            return new String[] {url, System.getenv().getOrDefault("IT_DB_USER", "postgres"),
                    System.getenv().getOrDefault("IT_DB_PASSWORD", "")};
        }
        if (pg == null) {
            pg = new PostgreSQLContainer<>("postgres:16-alpine");
            pg.start();
        }
        return new String[] {pg.getJdbcUrl(), pg.getUsername(), pg.getPassword()};
    }

    @BeforeEach
    void freshSchema() {
        String[] c = connection();
        schema = "dash_" + UUID.randomUUID().toString().replace("-", "");
        Flyway.configure().dataSource(c[0], c[1], c[2]).schemas(schema).createSchemas(true).load().migrate();
        jdbc = new JdbcTemplate(new DriverManagerDataSource(
                c[0] + (c[0].contains("?") ? "&" : "?") + "currentSchema=" + schema, c[1], c[2]));
        // the repeatable seed is the demo book; these tests build their own
        jdbc.update("delete from policies");
        when(policies.findAll()).thenReturn(List.of());
    }

    @AfterEach
    void dropSchema() {
        jdbc.execute("drop schema \"" + schema + "\" cascade");
    }

    private Dashboard dashboard() {
        return new DashboardService(jdbc, policies, CLOCK).dashboard();
    }

    private static Instant ist(String dateTime) {
        return LocalDateTime.parse(dateTime).atZone(IST).toInstant();
    }

    private void policy(String id, String name) {
        jdbc.update("""
                insert into policies(id, holder_name, date_of_birth, mobile_last4, product, sum_insured, expires_on,
                                     last_premium, renewal_premium)
                values (?, ?, '1980-01-01', '1234', 'Health Floater', 500000, '2026-12-01', 10000, 11000)
                """, id, name);
    }

    private UUID call(String policyId, String type, Instant startedAt, Instant endedAt, String outcome,
                      String quote, boolean mustHandoff) {
        UUID id = UUID.randomUUID();
        jdbc.update("""
                insert into cases(id, case_type, title, status, pipeline_version, created_by)
                values (?, ?, 't', 'PROCESSING', 'v1', 'it')""", id, type);
        jdbc.update("""
                insert into calls(id, policy_id, started_at, ended_at, outcome, last_quote, must_handoff)
                values (?, ?, ?, ?, ?, ?::jsonb, ?)""", id, policyId, Timestamp.from(startedAt),
                endedAt == null ? null : Timestamp.from(endedAt), outcome, quote, mustHandoff);
        return id;
    }

    private void audit(UUID caseId, String action, String payload, Instant at) {
        String zeros = "0".repeat(64);
        jdbc.update("""
                insert into audit_events(case_id, actor, action, payload, prev_hash, hash, created_at)
                values (?, 'voice', ?, ?::jsonb, ?, ?, ?)""", caseId, action, payload, zeros, zeros,
                Timestamp.from(at));
    }

    @Test
    void emptyDatabaseGivesZeros() {
        Dashboard d = dashboard();

        assertThat(d.kpis()).isEqualTo(new RenewalDtos.Kpis(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0));
        assertThat(d.recentCalls()).isEmpty();
        assertThat(d.guardrailEvents()).isEmpty();
        assertThat(d.outcomesByDay()).hasSize(7).allSatisfy(o ->
                assertThat(o.renewed() + o.handedOff() + o.noDecision()).isZero());
        assertThat(d.riskBands()).extracting(RenewalDtos.RiskBand::band)
                .containsExactly("0.0–0.2", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–1.0");
        assertThat(d.riskBands()).allSatisfy(b -> assertThat(b.count()).isZero());
    }

    @Test
    void inProgressIsNotCountedAsOutcome() {
        policy("P1", "Meera Iyer");
        call("P1", "renewal_call", ist("2026-10-29T09:30:00"), null, null, null, false);

        Dashboard d = dashboard();

        assertThat(d.kpis().callsTotal()).isEqualTo(1);
        assertThat(d.kpis().callsToday()).isEqualTo(1);
        assertThat(d.kpis().inProgress()).isEqualTo(1);
        assertThat(d.kpis().renewed() + d.kpis().handedOff() + d.kpis().noDecision()).isZero();
        assertThat(d.kpis().saveRate()).isZero();
        assertThat(d.outcomesByDay()).allSatisfy(o ->
                assertThat(o.renewed() + o.handedOff() + o.noDecision()).isZero());
        assertThat(d.recentCalls()).singleElement().satisfies(r -> {
            assertThat(r.outcome()).isNull();
            assertThat(r.endedAt()).isNull();
            assertThat(r.holderName()).isEqualTo("Meera Iyer");
        });
    }

    @Test
    void premiumRetainedSumsRenewedQuotes() {
        policy("P1", "Meera Iyer");
        call("P1", "renewal_call", ist("2026-10-29T09:00:00"), ist("2026-10-29T09:05:00"),
                "RENEWAL_PENDING_PAYMENT", "{\"annualPremium\":18450}", false);
        call("P1", "renewal_call", ist("2026-10-28T09:00:00"), ist("2026-10-28T09:05:00"),
                "RENEWAL_PENDING_PAYMENT", "{\"annualPremium\":10000}", false);
        call("P1", "renewal_call", ist("2026-10-28T10:00:00"), ist("2026-10-28T10:05:00"),
                "HANDED_OFF", "{\"annualPremium\":5000}", true);
        call("P1", "renewal_call", ist("2026-10-27T10:00:00"), ist("2026-10-27T10:05:00"),
                "NO_DECISION", null, false);

        var k = dashboard().kpis();

        assertThat(k.premiumRetained()).isEqualTo(28450);
        assertThat(k.renewed()).isEqualTo(2);
        assertThat(k.handedOff()).isEqualTo(1);
        assertThat(k.noDecision()).isEqualTo(1);
        assertThat(k.callsToday()).isEqualTo(1);
        assertThat(k.saveRate()).isEqualTo(0.5);
    }

    @Test
    void outcomesByDayZeroFillsSevenDays() {
        policy("P1", "Meera Iyer");
        // 00:30 IST on the 29th is still the 28th in UTC: the bucket must follow the clock zone
        call("P1", "renewal_call", ist("2026-10-29T00:10:00"), ist("2026-10-29T00:30:00"), "HANDED_OFF", null, true);
        call("P1", "renewal_call", ist("2026-10-27T11:00:00"), ist("2026-10-27T11:05:00"),
                "RENEWAL_PENDING_PAYMENT", "{\"annualPremium\":1}", false);
        call("P1", "renewal_call", ist("2026-10-27T12:00:00"), ist("2026-10-27T12:05:00"), "NO_DECISION", null, false);
        call("P1", "renewal_call", ist("2026-10-23T12:00:00"), ist("2026-10-23T12:05:00"), "NO_DECISION", null, false);
        call("P1", "renewal_call", ist("2026-10-22T12:00:00"), ist("2026-10-22T12:05:00"), "NO_DECISION", null, false);

        var days = dashboard().outcomesByDay();

        assertThat(days).extracting(RenewalDtos.DayOutcomes::day).containsExactly(
                TODAY.minusDays(6), TODAY.minusDays(5), TODAY.minusDays(4), TODAY.minusDays(3),
                TODAY.minusDays(2), TODAY.minusDays(1), TODAY);
        assertThat(days.get(0)).isEqualTo(new RenewalDtos.DayOutcomes(LocalDate.of(2026, 10, 23), 0, 0, 1));
        assertThat(days.get(4)).isEqualTo(new RenewalDtos.DayOutcomes(LocalDate.of(2026, 10, 27), 1, 0, 1));
        assertThat(days.get(5)).isEqualTo(new RenewalDtos.DayOutcomes(LocalDate.of(2026, 10, 28), 0, 0, 0));
        assertThat(days.get(6)).isEqualTo(new RenewalDtos.DayOutcomes(TODAY, 0, 1, 0));
        assertThat(days.stream().mapToLong(d -> d.renewed() + d.handedOff() + d.noDecision()).sum()).isEqualTo(4);
    }

    @Test
    void guardrailEventsNewestFirstAndFiltered() {
        policy("P1", "Meera Iyer");
        policy("P2", "Rohan Das");
        UUID a = call("P1", "renewal_call", ist("2026-10-29T09:00:00"), null, null, null, false);
        UUID b = call("P2", "renewal_call", ist("2026-10-29T09:10:00"), null, null, null, false);
        UUID other = call("P1", "other_case", ist("2026-10-29T09:20:00"), null, null, null, false);
        audit(a, "call.started", "{}", ist("2026-10-29T09:00:00"));
        audit(a, "identity.failed", "{\"attempt\":1,\"mustHandoff\":false}", ist("2026-10-29T09:01:00"));
        audit(a, "rule.outside_playbook",
                "{\"requestedDiscountPercent\":25,\"maxDiscountPercent\":10,\"count\":1}", ist("2026-10-29T09:02:00"));
        audit(b, "tool.refused", "{\"tool\":\"quote\",\"code\":\"IDENTITY_NOT_VERIFIED\"}", ist("2026-10-29T09:11:00"));
        audit(b, "tool.handoff_to_human", "{\"reason\":\"Customer wants a manager\"}", ist("2026-10-29T09:12:00"));
        audit(b, "call.ended", "{\"outcome\":\"HANDED_OFF\"}", ist("2026-10-29T09:13:00"));
        audit(other, "tool.refused", "{\"tool\":\"x\",\"code\":\"NOPE\"}", ist("2026-10-29T09:30:00"));

        Dashboard d = dashboard();

        assertThat(d.guardrailEvents()).extracting(RenewalDtos.GuardrailEvent::action).containsExactly(
                "tool.handoff_to_human", "tool.refused", "rule.outside_playbook", "identity.failed");
        assertThat(d.guardrailEvents()).extracting(RenewalDtos.GuardrailEvent::detail).containsExactly(
                "Customer wants a manager", "IDENTITY_NOT_VERIFIED", "Asked for 25% discount, limit 10%",
                "Attempt 1");
        assertThat(d.guardrailEvents()).extracting(RenewalDtos.GuardrailEvent::holderName)
                .containsExactly("Rohan Das", "Rohan Das", "Meera Iyer", "Meera Iyer");
        assertThat(d.guardrailEvents().get(0).callId()).isEqualTo(b);
        assertThat(d.kpis().blockedRequests()).isEqualTo(1);
        assertThat(d.kpis().refusals()).isEqualTo(1);
        assertThat(d.kpis().identityFailures()).isEqualTo(1);
    }

    @Test
    void guardrailEventsAreCappedAtThirty() {
        policy("P1", "Meera Iyer");
        UUID a = call("P1", "renewal_call", ist("2026-10-29T09:00:00"), null, null, null, false);
        for (int i = 0; i < 35; i++) {
            audit(a, "tool.refused", "{\"tool\":\"t\",\"code\":\"C" + i + "\"}", ist("2026-10-29T09:00:00").plusSeconds(i));
        }

        var events = dashboard().guardrailEvents();

        assertThat(events).hasSize(30);
        assertThat(events.get(0).detail()).isEqualTo("C34");
    }

    @Test
    void riskBandsCoverQueue() {
        PolicyEntity hot = PolicyFixtures.with(PolicyFixtures.meera(), "doNotCall", false);
        PolicyEntity human = PolicyFixtures.with(PolicyFixtures.policy("P-H", "Human Only", "2026-11-03", 10000, 12000),
                "openComplaint", true);
        PolicyEntity calm = PolicyFixtures.policy("P-C", "Calm Customer", "2027-03-01", 10000, 10000);
        PolicyEntity expired = PolicyFixtures.policy("P-E", "Expired", "2026-10-01", 10000, 12000);
        when(policies.findAll()).thenReturn(List.of(hot, human, calm, expired));

        Dashboard d = dashboard();

        assertThat(d.riskBands()).hasSize(5);
        assertThat(d.riskBands().stream().mapToLong(RenewalDtos.RiskBand::count).sum()).isEqualTo(3);
        assertThat(d.riskBands().stream().mapToLong(RenewalDtos.RiskBand::agentCall).sum()).isEqualTo(1);
        assertThat(d.riskBands().stream().mapToLong(RenewalDtos.RiskBand::humanOnly).sum()).isEqualTo(1);
        assertThat(d.riskBands().stream().mapToLong(RenewalDtos.RiskBand::reminderSms).sum()).isEqualTo(1);
        assertThat(d.riskBands().get(0).reminderSms()).isEqualTo(1);
        // agent-call and human-only renewals are the premium still at stake; reminders and expired are not
        assertThat(d.kpis().premiumAtRisk()).isEqualTo(18450 + 12000);
    }
}
