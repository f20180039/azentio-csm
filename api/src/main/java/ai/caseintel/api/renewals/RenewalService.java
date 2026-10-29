package ai.caseintel.api.renewals;

import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.config.AppProperties;
import ai.caseintel.api.domain.CaseEntity;
import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.renewals.RenewalDtos.QueueItem;
import ai.caseintel.api.renewals.RenewalDtos.Risk;
import ai.caseintel.api.renewals.RenewalDtos.StartedCall;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.service.ApiException;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.temporal.ChronoUnit;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class RenewalService {

    static final String CASE_TYPE = "renewal_call";
    private static final LocalTime CALLS_FROM = LocalTime.of(9, 0);
    private static final LocalTime CALLS_UNTIL = LocalTime.of(21, 0);

    private final PolicyRepository policies;
    private final CallRepository calls;
    private final CaseRepository cases;
    private final AuditService audit;
    private final Playbook playbook;
    private final Clock clock;
    private final AppProperties props;
    private final ObjectMapper mapper;

    public RenewalService(PolicyRepository policies, CallRepository calls, CaseRepository cases, AuditService audit,
                          Playbook playbook, Clock clock, AppProperties props, ObjectMapper mapper) {
        this.policies = policies;
        this.calls = calls;
        this.cases = cases;
        this.audit = audit;
        this.playbook = playbook;
        this.clock = clock;
        this.props = props;
        this.mapper = mapper;
    }

    @PreAuthorize("hasRole('ANALYST')")
    @Transactional(readOnly = true)
    public List<QueueItem> queue() {
        LocalDate today = LocalDate.now(clock);
        return policies.findAll().stream()
                .filter(p -> !p.getExpiresOn().isBefore(today))
                .map(p -> {
                    Risk r = LapseRisk.assess(p, today);
                    return new QueueItem(p.getId(), p.getHolderName(), p.getProduct(), p.getExpiresOn(),
                            (int) ChronoUnit.DAYS.between(today, p.getExpiresOn()), r.score(), r.signals(), r.route());
                })
                .sorted(Comparator.comparing(QueueItem::score).reversed().thenComparingInt(QueueItem::daysToExpiry))
                .toList();
    }

    @PreAuthorize("hasRole('ANALYST')")
    @Transactional
    public StartedCall startCall(String policyId, String actor) {
        if (policyId == null || policyId.isBlank()) {
            throw ApiException.badRequest("policyId is required");
        }
        PolicyEntity p = policies.findById(policyId)
                .orElseThrow(() -> ApiException.notFound("Policy " + policyId + " not found"));
        if (p.isOpenComplaint()) {
            throw ApiException.conflict("HUMAN_ONLY");
        }
        if (p.isDoNotCall()) {
            throw ApiException.conflict("DO_NOT_CALL");
        }
        if (props.renewals().enforceCallingHours()) {
            LocalTime now = LocalTime.now(clock);
            if (now.isBefore(CALLS_FROM) || !now.isBefore(CALLS_UNTIL)) {
                throw ApiException.conflict("OUTSIDE_CALLING_HOURS");
            }
        }
        Instant now = clock.instant();
        UUID id = UUID.randomUUID();
        CaseEntity c = new CaseEntity(id, CASE_TYPE, "Renewal call · " + p.getHolderName(),
                json(Map.of("policyId", p.getId())), props.pipelineVersion(), actor, now);
        c.setStatus(CaseStatus.PROCESSING);
        cases.save(c);
        calls.save(new CallEntity(id, p.getId(), now));
        audit.record(id, actor, "call.started", Map.of("policyId", p.getId(), "playbook", playbook.id(),
                "playbookVersion", playbook.version()));
        return new StartedCall(id, id, playbook.greeting().replace("{holderName}", p.getHolderName()));
    }

    private String json(Object o) {
        try {
            return mapper.writeValueAsString(o);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }
}
