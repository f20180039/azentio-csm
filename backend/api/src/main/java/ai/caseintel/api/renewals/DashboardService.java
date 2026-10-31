package ai.caseintel.api.renewals;

import ai.caseintel.api.renewals.RenewalDtos.Dashboard;
import ai.caseintel.api.renewals.RenewalDtos.DayOutcomes;
import ai.caseintel.api.renewals.RenewalDtos.GuardrailEvent;
import ai.caseintel.api.renewals.RenewalDtos.Kpis;
import ai.caseintel.api.renewals.RenewalDtos.RecentCall;
import ai.caseintel.api.renewals.RenewalDtos.RiskBand;
import ai.caseintel.api.renewals.RenewalDtos.Risk;
import java.math.BigDecimal;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import ai.caseintel.api.service.ApiException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Read-only aggregates for the operations dashboard: a fixed number of queries, none per call. */
@Service
public class DashboardService {

    private static final String RENEWED = "RENEWAL_PENDING_PAYMENT";
    private static final int DAYS = 7;
    private static final int BANDS = 5;
    /** A bound flag: true lets simulated calls through, false keeps only real ones. */
    private static final String REAL_OR_ALL = "(? OR NOT c.attributes @> '{\"simulated\": true}')";

    private static final String CALL_TOTALS = """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE started_at >= ?) AS today,
                   count(*) FILTER (WHERE outcome IS NULL) AS in_progress,
                   count(*) FILTER (WHERE outcome = 'RENEWAL_PENDING_PAYMENT') AS renewed,
                   count(*) FILTER (WHERE outcome = 'HANDED_OFF') AS handed_off,
                   count(*) FILTER (WHERE outcome = 'NO_DECISION') AS no_decision,
                   count(*) FILTER (WHERE ended_at IS NOT NULL) AS ended,
                   COALESCE(sum((last_quote ->> 'annualPremium')::numeric)
                            FILTER (WHERE outcome = 'RENEWAL_PENDING_PAYMENT'), 0) AS retained
            FROM calls k JOIN cases c ON c.id = k.id
            WHERE k.kind = 'RENEWAL' AND """ + REAL_OR_ALL;

    private static final String AUDIT_COUNTS = """
            SELECT a.action, count(*) AS n
            FROM audit_events a JOIN cases c ON c.id = a.case_id
            WHERE c.case_type = 'renewal_call'
              AND a.action IN ('rule.outside_playbook', 'tool.refused', 'identity.failed')
              AND """ + REAL_OR_ALL + """
            GROUP BY a.action""";

    private static final String BY_DAY = """
            SELECT (ended_at AT TIME ZONE ?)::date AS day, outcome, count(*) AS n
            FROM calls k JOIN cases c ON c.id = k.id
            WHERE k.kind = 'RENEWAL' AND outcome IS NOT NULL AND ended_at >= ? AND """ + REAL_OR_ALL + """
            GROUP BY 1, 2""";

    private static final String RECENT = """
            SELECT k.id, p.holder_name, k.policy_id, p.product, k.started_at, k.ended_at, k.outcome,
                   k.must_handoff, k.out_of_playbook_requests
            FROM calls k JOIN policies p ON p.id = k.policy_id JOIN cases c ON c.id = k.id
            WHERE k.kind = 'RENEWAL' AND """ + REAL_OR_ALL + """
            ORDER BY k.started_at DESC LIMIT 20""";

    private static final String GUARDRAILS = """
            SELECT a.created_at, a.case_id, p.holder_name, a.action,
                   CASE a.action
                       WHEN 'tool.refused' THEN a.payload ->> 'code'
                       WHEN 'tool.handoff_to_human' THEN a.payload ->> 'reason'
                       WHEN 'rule.outside_playbook' THEN 'Asked for ' || (a.payload ->> 'requestedDiscountPercent')
                            || '% discount, limit ' || (a.payload ->> 'maxDiscountPercent') || '%'
                       WHEN 'identity.failed' THEN 'Attempt ' || (a.payload ->> 'attempt')
                   END AS detail
            FROM audit_events a
            JOIN cases c ON c.id = a.case_id AND c.case_type = 'renewal_call'
            JOIN calls k ON k.id = a.case_id AND k.kind = 'RENEWAL'
            JOIN policies p ON p.id = k.policy_id
            WHERE a.action IN ('rule.outside_playbook', 'tool.refused', 'identity.failed', 'tool.handoff_to_human')
              AND """ + REAL_OR_ALL + """
            ORDER BY a.created_at DESC, a.id DESC LIMIT 30""";

    private static final String MARK_SIMULATED = """
            UPDATE cases SET attributes = attributes || '{"simulated": true}'::jsonb
            WHERE id = ? AND case_type = 'renewal_call'""";

    private final JdbcTemplate jdbc;
    private final PolicyRepository policies;
    private final Clock clock;

    public DashboardService(JdbcTemplate jdbc, PolicyRepository policies, Clock clock) {
        this.jdbc = jdbc;
        this.policies = policies;
        this.clock = clock;
    }

    @PreAuthorize("hasRole('ANALYST')")
    @Transactional(readOnly = true)
    public Dashboard dashboard() {
        return dashboard(false);
    }

    @PreAuthorize("hasRole('ANALYST')")
    @Transactional(readOnly = true)
    public Dashboard dashboard(boolean includeSimulated) {
        LocalDate today = LocalDate.now(clock);
        ZoneId zone = clock.getZone();
        Timestamp startOfToday = Timestamp.from(today.atStartOfDay(zone).toInstant());

        long[] totals = jdbc.queryForObject(CALL_TOTALS, (rs, i) -> new long[] {
                rs.getLong("total"), rs.getLong("today"), rs.getLong("in_progress"), rs.getLong("renewed"),
                rs.getLong("handed_off"), rs.getLong("no_decision"), rs.getLong("ended"),
                rs.getBigDecimal("retained").longValue()}, startOfToday, includeSimulated);

        Map<String, Long> audit = new HashMap<>();
        jdbc.query(AUDIT_COUNTS, rs -> {
            audit.put(rs.getString("action"), rs.getLong("n"));
        }, includeSimulated);

        long[][] tally = new long[BANDS][3];
        long atRisk = 0;
        for (PolicyEntity p : policies.findAll()) {
            if (p.getExpiresOn().isBefore(today)) {
                continue;
            }
            Risk r = LapseRisk.assess(p, today);
            int band = Math.min(BANDS - 1, r.score().multiply(BigDecimal.valueOf(BANDS))
                    .setScale(0, java.math.RoundingMode.FLOOR).intValue());
            tally[band][r.route().ordinal()]++;
            if (r.route() != RenewalDtos.Route.REMINDER_SMS) {
                atRisk += p.getRenewalPremium().longValue();
            }
        }
        List<RiskBand> bands = new ArrayList<>();
        for (int i = 0; i < BANDS; i++) {
            long[] t = tally[i];
            bands.add(new RiskBand(String.format("%.1f–%.1f", i * 0.2, (i + 1) * 0.2), t[0] + t[1] + t[2],
                    t[RenewalDtos.Route.AGENT_CALL.ordinal()], t[RenewalDtos.Route.HUMAN_ONLY.ordinal()],
                    t[RenewalDtos.Route.REMINDER_SMS.ordinal()]));
        }

        long ended = totals[6];
        Kpis kpis = new Kpis(totals[1], totals[0], totals[2], totals[3], totals[4], totals[5], totals[7], atRisk,
                audit.getOrDefault("rule.outside_playbook", 0L), audit.getOrDefault("tool.refused", 0L),
                audit.getOrDefault("identity.failed", 0L), ended == 0 ? 0 : (double) totals[3] / ended);

        return new Dashboard(kpis, outcomesByDay(today, zone, includeSimulated), recentCalls(includeSimulated),
                guardrailEvents(includeSimulated), bands);
    }

    /** Tags existing renewal calls as simulated; returns how many were found. */
    @PreAuthorize("hasRole('ADMIN')")
    @Transactional
    public int markSimulated(List<UUID> callIds) {
        if (callIds == null || callIds.isEmpty()) {
            throw ApiException.badRequest("callIds is required");
        }
        int marked = 0;
        for (UUID id : callIds) {
            marked += jdbc.update(MARK_SIMULATED, id);
        }
        return marked;
    }

    private List<DayOutcomes> outcomesByDay(LocalDate today, ZoneId zone, boolean includeSimulated) {
        LocalDate first = today.minusDays(DAYS - 1);
        Map<LocalDate, long[]> byDay = new HashMap<>();
        jdbc.query(BY_DAY, rs -> {
            long[] row = byDay.computeIfAbsent(rs.getObject("day", LocalDate.class), d -> new long[3]);
            switch (rs.getString("outcome")) {
                case RENEWED -> row[0] += rs.getLong("n");
                case "HANDED_OFF" -> row[1] += rs.getLong("n");
                default -> row[2] += rs.getLong("n");
            }
        }, zone.getId(), Timestamp.from(first.atStartOfDay(zone).toInstant()), includeSimulated);
        List<DayOutcomes> out = new ArrayList<>();
        for (int i = 0; i < DAYS; i++) {
            LocalDate d = first.plusDays(i);
            long[] r = byDay.getOrDefault(d, new long[3]);
            out.add(new DayOutcomes(d, r[0], r[1], r[2]));
        }
        return out;
    }

    private List<RecentCall> recentCalls(boolean includeSimulated) {
        return jdbc.query(RECENT, (rs, i) -> new RecentCall(rs.getObject("id", UUID.class),
                rs.getString("holder_name"), rs.getString("policy_id"), rs.getString("product"),
                instant(rs.getTimestamp("started_at")), instant(rs.getTimestamp("ended_at")),
                rs.getString("outcome"), rs.getBoolean("must_handoff"), rs.getInt("out_of_playbook_requests")),
                includeSimulated);
    }

    private List<GuardrailEvent> guardrailEvents(boolean includeSimulated) {
        return jdbc.query(GUARDRAILS, (rs, i) -> new GuardrailEvent(instant(rs.getTimestamp("created_at")),
                rs.getObject("case_id", UUID.class), rs.getString("holder_name"), rs.getString("action"),
                rs.getString("detail")), includeSimulated);
    }

    private static Instant instant(Timestamp t) {
        return t == null ? null : t.toInstant();
    }
}
