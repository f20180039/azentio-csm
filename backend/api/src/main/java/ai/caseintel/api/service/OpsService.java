package ai.caseintel.api.service;

import ai.caseintel.api.agent.AgentClient;
import ai.caseintel.api.audit.AuditChain;
import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.jobs.JobQueue;
import ai.caseintel.api.rules.PackRegistry;
import ai.caseintel.api.service.Dtos.PackView;
import ai.caseintel.api.service.Dtos.RuleView;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Service;

@Service
public class OpsService {

    private final PackRegistry packs;
    private final JdbcTemplate jdbc;
    private final JobQueue jobs;
    private final ProcessingMetrics metrics;
    private final AuditService audit;
    private final AgentClient agent;

    public OpsService(PackRegistry packs, JdbcTemplate jdbc, JobQueue jobs, ProcessingMetrics metrics,
                      AuditService audit, AgentClient agent) {
        this.packs = packs;
        this.jdbc = jdbc;
        this.jobs = jobs;
        this.metrics = metrics;
        this.audit = audit;
        this.agent = agent;
    }

    @PreAuthorize("hasRole('ANALYST')")
    public List<PackView> packs() {
        return packs.all().stream()
                .sorted(Comparator.comparing(p -> p.code().caseType()))
                .map(p -> new PackView(p.code().caseType(), p.config().label(), p.code().extractionSchema(),
                        p.config().routing().autoClearBelow(), p.config().routing().escalateAtOrAbove(),
                        p.rules().stream().map(r -> {
                            var rc = p.config().rules().get(r.id());
                            return new RuleView(r.id(), packs.isCore(r.id()), rc.weight(), rc.rationale(), rc.params());
                        }).toList()))
                .toList();
    }

    @PreAuthorize("hasRole('ANALYST')")
    public Dtos.Stats stats() {
        Map<String, Long> byStatus = new LinkedHashMap<>();
        jdbc.query("select status, count(*) n from cases group by status order by status",
                rs -> {
                    byStatus.put(rs.getString("status"), rs.getLong("n"));
                });
        return new Dtos.Stats(byStatus, jobs.pendingCount(), metrics.percentile(0.5), metrics.percentile(0.95),
                metrics.samples(), metrics.cacheHits(), metrics.cacheMisses());
    }

    @PreAuthorize("hasRole('ADMIN')")
    public AuditChain.Verification verifyAudit() {
        return audit.verifyAll();
    }

    public Dtos.Health health() {
        String db;
        try {
            jdbc.queryForObject("select 1", Integer.class);
            db = "UP";
        } catch (RuntimeException e) {
            db = "DOWN";
        }
        String agentStatus = agent.healthy() ? "UP" : "DOWN";
        String overall = "UP".equals(db) && "UP".equals(agentStatus) ? "UP" : "DEGRADED";
        return new Dtos.Health(overall, db, agentStatus);
    }
}
