package ai.caseintel.api.renewals;

import static ai.caseintel.api.renewals.PolicyFixtures.meera;
import static ai.caseintel.api.renewals.PolicyFixtures.policy;
import static ai.caseintel.api.renewals.PolicyFixtures.rohan;
import static ai.caseintel.api.renewals.PolicyFixtures.with;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.config.AppProperties;
import ai.caseintel.api.domain.CaseEntity;
import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.renewals.RenewalDtos.QueueItem;
import ai.caseintel.api.renewals.RenewalDtos.Route;
import ai.caseintel.api.renewals.RenewalDtos.StartedCall;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.service.ApiException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.ZoneId;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.http.HttpStatus;

class RenewalServiceTest {

    private static final ZoneId IST = ZoneId.of("Asia/Kolkata");

    private final PolicyRepository policies = mock(PolicyRepository.class);
    private final CallRepository calls = mock(CallRepository.class);
    private final CaseRepository cases = mock(CaseRepository.class);
    private final AuditService audit = mock(AuditService.class);
    private final Playbook playbook = PlaybookLoader.load("playbooks/health-renewal.yml");

    private RenewalService service(String istDateTime, boolean enforce) {
        Clock clock = Clock.fixed(java.time.LocalDateTime.parse(istDateTime).atZone(IST).toInstant(), IST);
        AppProperties props = new AppProperties(null, null, null, null, null, null, null,
                new AppProperties.Renewals(enforce, "playbooks/health-renewal.yml"));
        return new RenewalService(policies, calls, cases, audit, playbook, clock, props, new ObjectMapper());
    }

    @BeforeEach
    void setUp() {
        when(policies.findAll()).thenReturn(List.of(rohan(), meera(),
                with(policy("HF-0000-0001", "Arjun Mehta", "2026-11-10", 100, 100), "openComplaint", true),
                policy("HF-0000-0002", "Lapsed Lata", "2026-10-20", 100, 100)));
    }

    @Test
    void queueIsSortedAndExcludesExpired() {
        List<QueueItem> q = service("2026-10-29T11:00:00", true).queue();
        assertThat(q).extracting(QueueItem::policyId)
                .containsExactly("HF-2291-0457", "HF-0000-0001", "HF-1180-0233");
        assertThat(q.get(0).daysToExpiry()).isEqualTo(5);
        assertThat(q.get(0).route()).isEqualTo(Route.AGENT_CALL);
        assertThat(q.get(1).route()).isEqualTo(Route.HUMAN_ONLY);
    }

    @Test
    void humanOnlyPolicyCannotBeCalled() {
        when(policies.findById("HF-0000-0001")).thenReturn(Optional.of(
                with(policy("HF-0000-0001", "Arjun Mehta", "2026-11-10", 100, 100), "openComplaint", true)));
        assertConflict(() -> service("2026-10-29T11:00:00", true).startCall("HF-0000-0001", "analyst"), "HUMAN_ONLY");
        when(policies.findById("HF-0000-0003")).thenReturn(Optional.of(
                with(policy("HF-0000-0003", "Dnc Dev", "2026-11-10", 100, 100), "doNotCall", true)));
        assertConflict(() -> service("2026-10-29T11:00:00", true).startCall("HF-0000-0003", "analyst"), "DO_NOT_CALL");
        verify(cases, never()).save(any());
    }

    @Test
    void outsideCallingHoursIsRefused() {
        when(policies.findById("HF-2291-0457")).thenReturn(Optional.of(meera()));
        assertConflict(() -> service("2026-10-29T21:30:00", true).startCall("HF-2291-0457", "analyst"),
                "OUTSIDE_CALLING_HOURS");
        assertConflict(() -> service("2026-10-29T08:59:00", true).startCall("HF-2291-0457", "analyst"),
                "OUTSIDE_CALLING_HOURS");
        assertThat(service("2026-10-29T21:30:00", false).startCall("HF-2291-0457", "analyst")).isNotNull();
        assertThat(service("2026-10-29T09:00:00", true).startCall("HF-2291-0457", "analyst")).isNotNull();
    }

    @Test
    void unknownPolicyIs404() {
        when(policies.findById("x")).thenReturn(Optional.empty());
        assertThatThrownBy(() -> service("2026-10-29T11:00:00", true).startCall("x", "analyst"))
                .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.status()).isEqualTo(HttpStatus.NOT_FOUND));
    }

    @Test
    void startCallCreatesCaseCallRowAndAudit() {
        when(policies.findById("HF-2291-0457")).thenReturn(Optional.of(meera()));
        StartedCall r = service("2026-10-29T11:00:00", true).startCall("HF-2291-0457", "analyst");

        ArgumentCaptor<CaseEntity> cc = ArgumentCaptor.forClass(CaseEntity.class);
        verify(cases).save(cc.capture());
        CaseEntity c = cc.getValue();
        assertThat(c.getCaseType()).isEqualTo("renewal_call");
        assertThat(c.getTitle()).isEqualTo("Renewal call · Meera Iyer");
        assertThat(c.getStatus()).isEqualTo(CaseStatus.PROCESSING);
        assertThat(c.getAttributes()).isEqualTo("{\"policyId\":\"HF-2291-0457\"}");

        ArgumentCaptor<CallEntity> call = ArgumentCaptor.forClass(CallEntity.class);
        verify(calls).save(call.capture());
        assertThat(call.getValue().getId()).isEqualTo(c.getId());
        assertThat(call.getValue().getPolicyId()).isEqualTo("HF-2291-0457");

        verify(audit).record(eq(c.getId()), eq("analyst"), eq("call.started"), anyMap());
        assertThat(r.callId()).isEqualTo(c.getId());
        assertThat(r.caseId()).isEqualTo(c.getId());
        assertThat(r.greeting()).isEqualTo("Hello, this call is recorded. I'm the renewals assistant from "
                + "Lotusleaf General Insurance. Am I speaking with Meera Iyer?");
    }

    private static void assertConflict(Runnable r, String detail) {
        assertThatThrownBy(r::run).isInstanceOfSatisfying(ApiException.class, e -> {
            assertThat(e.status()).isEqualTo(HttpStatus.CONFLICT);
            assertThat(e.getMessage()).isEqualTo(detail);
        });
    }
}
