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
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import ai.caseintel.api.audit.AuditRow;
import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.config.AppProperties;
import ai.caseintel.api.domain.CaseEntity;
import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.renewals.RenewalDtos.CallView;
import ai.caseintel.api.renewals.RenewalDtos.HandoffRequest;
import ai.caseintel.api.renewals.RenewalDtos.Options;
import ai.caseintel.api.renewals.RenewalDtos.PolicyView;
import ai.caseintel.api.renewals.RenewalDtos.Quote;
import ai.caseintel.api.renewals.RenewalDtos.QuoteRequest;
import ai.caseintel.api.renewals.RenewalDtos.QueueItem;
import ai.caseintel.api.renewals.RenewalDtos.TurnRequest;
import ai.caseintel.api.renewals.RenewalDtos.Verification;
import ai.caseintel.api.renewals.RenewalDtos.Route;
import ai.caseintel.api.renewals.RenewalDtos.StartedCall;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.service.ApiException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.ZoneId;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.Optional;
import com.fasterxml.jackson.databind.JsonNode;
import java.time.LocalDate;
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
    private final List<AuditRow> events = new ArrayList<>();
    private CallEntity callRow;
    private CaseEntity caseRow;
    private final Playbook playbook = PlaybookLoader.load("playbooks/health-renewal.yml");

    private RenewalService service(String istDateTime, boolean enforce) {
        Clock clock = Clock.fixed(java.time.LocalDateTime.parse(istDateTime).atZone(IST).toInstant(), IST);
        AppProperties props = new AppProperties(null, null, null, null, null, null, null,
                new AppProperties.Renewals(enforce, "playbooks/health-renewal.yml"));
        return new RenewalService(policies, calls, cases, audit, playbook, clock, props, new ObjectMapper());
    }

    @BeforeEach
    void setUp() {
        when(calls.findForUpdate(any())).thenAnswer(i -> Optional.ofNullable(callRow));
        when(calls.findById(any())).thenAnswer(i -> Optional.ofNullable(callRow));
        when(cases.findById(any())).thenAnswer(i -> Optional.ofNullable(caseRow));
        doAnswer(i -> {
            events.add(new AuditRow(events.size() + 1L, i.getArgument(0), i.getArgument(1), i.getArgument(2),
                    new ObjectMapper().valueToTree(i.getArgument(3)), "p", "h", Instant.now()));
            return null;
        }).when(audit).record(any(), any(), any(), any());
        when(audit.forCase(any())).thenAnswer(i -> events);
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

    // ---- tool endpoints ----

    private static final String WHEN = "2026-10-29T11:00:00";

    private RenewalService startedCall() {
        RenewalService s = service(WHEN, true);
        PolicyEntity meera = meera();
        PolicyFixtures.with(meera, "dateOfBirth", LocalDate.of(1980, 3, 14));
        PolicyFixtures.with(meera, "mobileLast4", "4821");
        PolicyFixtures.with(meera, "sumInsured", java.math.BigDecimal.valueOf(1000000));
        PolicyFixtures.with(meera, "premiumBreakdown",
                "[{\"label\":\"Age band\",\"amount\":2610},{\"label\":\"Medical inflation\",\"amount\":720}]");
        PolicyFixtures.with(meera, "addons",
                "[{\"code\":\"OPD\",\"name\":\"Outpatient cover\",\"premium\":2100,\"optional\":true},"
                        + "{\"code\":\"BASE\",\"name\":\"Base cover\",\"premium\":9000,\"optional\":false}]");
        when(policies.findById("HF-2291-0457")).thenReturn(Optional.of(meera));
        UUID id = s.startCall("HF-2291-0457", "analyst").callId();
        ArgumentCaptor<CallEntity> cc = ArgumentCaptor.forClass(CallEntity.class);
        verify(calls, atLeastOnce()).save(cc.capture());
        callRow = cc.getValue();
        ArgumentCaptor<CaseEntity> cs = ArgumentCaptor.forClass(CaseEntity.class);
        verify(cases, atLeastOnce()).save(cs.capture());
        caseRow = cs.getValue();
        assertThat(id).isEqualTo(callRow.getId());
        return s;
    }

    private RenewalService verifiedCall() {
        RenewalService s = startedCall();
        assertThat(s.verify(callRow.getId(), "1980-03-14", "voice").verified()).isTrue();
        return s;
    }

    private UUID id() {
        return callRow.getId();
    }

    private static void assertRefused(Runnable r, HttpStatus status, String code) {
        assertThatThrownBy(r::run).isInstanceOfSatisfying(ApiException.class, e -> {
            assertThat(e.status()).isEqualTo(status);
            assertThat(e.getMessage()).isEqualTo(code);
        });
    }

    private List<String> actions() {
        return events.stream().map(AuditRow::action).toList();
    }

    @Test
    void policyBeforeVerifyIsRefused() {
        RenewalService s = startedCall();
        assertRefused(() -> s.policy(id(), "voice"), HttpStatus.FORBIDDEN, "IDENTITY_NOT_VERIFIED");
        assertRefused(() -> s.options(id(), "voice"), HttpStatus.FORBIDDEN, "IDENTITY_NOT_VERIFIED");
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "annual", 0), "voice"),
                HttpStatus.FORBIDDEN, "IDENTITY_NOT_VERIFIED");
        assertRefused(() -> s.paymentLink(id(), UUID.randomUUID(), "voice"),
                HttpStatus.FORBIDDEN, "IDENTITY_NOT_VERIFIED");
        assertThat(actions()).doesNotContain("tool.get_policy");
    }

    @Test
    void policyAfterVerifyShowsRenewalDetail() {
        RenewalService s = verifiedCall();
        PolicyView v = s.policy(id(), "voice");
        assertThat(v.policyId()).isEqualTo("HF-2291-0457");
        assertThat(v.renewalPremium()).isEqualTo(18450);
        assertThat(v.lastPremium()).isEqualTo(15120);
        assertThat(v.mobileLast4()).isEqualTo("4821");
        assertThat(v.breakdown()).hasSize(2);
        assertThat(v.mustHandoff()).isFalse();
        assertThat(actions()).containsSubsequence("call.started", "identity.verified", "tool.get_policy");
        Options o = s.options(id(), "voice");
        assertThat(o.removableAddons()).singleElement().satisfies(a -> {
            assertThat(a.code()).isEqualTo("OPD");
            assertThat(a.saving()).isEqualTo(2100);
        });
        assertThat(o.paymentPlans()).containsExactly("annual", "quarterly");
        assertThat(o.maxDiscountPercent()).isZero();
        assertThat(actions()).contains("tool.list_allowed_options");
    }

    @Test
    void wrongDobCountsDown() {
        RenewalService s = startedCall();
        Verification a = s.verify(id(), "1980-03-15", "voice");
        assertThat(a.verified()).isFalse();
        assertThat(a.attemptsLeft()).isEqualTo(2);
        assertThat(s.verify(id(), "1999-01-01", "voice").attemptsLeft()).isEqualTo(1);
        assertThat(actions()).contains("identity.failed").doesNotContain("identity.verified");
        assertThat(s.verify(id(), "1980-03-14", "voice").verified()).isTrue();
    }

    @Test
    void thirdFailedVerifyForcesHandoff() {
        RenewalService s = startedCall();
        s.verify(id(), "1980-03-15", "voice");
        s.verify(id(), "1980-03-16", "voice");
        Verification last = s.verify(id(), "1980-03-17", "voice");
        assertThat(last.attemptsLeft()).isZero();
        assertThat(last.mustHandoff()).isTrue();
        assertRefused(() -> s.verify(id(), "1980-03-14", "voice"), HttpStatus.CONFLICT, "VERIFY_LOCKED");
        assertRefused(() -> s.policy(id(), "voice"), HttpStatus.FORBIDDEN, "IDENTITY_NOT_VERIFIED");
    }

    @Test
    void malformedDobIsBadRequest() {
        RenewalService s = startedCall();
        assertThatThrownBy(() -> s.verify(id(), "14/03/1980", "voice")).isInstanceOfSatisfying(ApiException.class,
                e -> assertThat(e.status()).isEqualTo(HttpStatus.BAD_REQUEST));
        assertThat(callRow.getVerifyFailures()).isZero();
    }

    @Test
    void quoteDropsOpdQuarterly() {
        RenewalService s = verifiedCall();
        Quote q = s.quote(id(), new QuoteRequest(List.of("OPD"), "quarterly", 0), "voice");
        assertThat(q.annualPremium()).isEqualTo(16350);
        assertThat(q.instalments()).isEqualTo(4);
        assertThat(q.perInstalment()).isEqualTo(4088);
        assertThat(q.quoteId()).isNotNull();
        assertThat(callRow.getLastQuote()).contains(q.quoteId().toString());
        assertThat(actions()).contains("tool.quote_renewal");
        Quote annual = s.quote(id(), new QuoteRequest(List.of(), "annual", 0), "voice");
        assertThat(annual.annualPremium()).isEqualTo(18450);
        assertThat(annual.instalments()).isEqualTo(1);
        assertThat(annual.perInstalment()).isEqualTo(18450);
    }

    @Test
    void nonOptionalAddonIsInvalid() {
        RenewalService s = verifiedCall();
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of("BASE"), "annual", 0), "voice"),
                HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_OPTION");
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of("NOPE"), "annual", 0), "voice"),
                HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_OPTION");
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "monthly", 0), "voice"),
                HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_OPTION");
        assertThat(callRow.getLastQuote()).isNull();
        assertThat(callRow.getOutOfPlaybookRequests()).isZero();
    }

    @Test
    void discountIsCheckedBeforeOptions() {
        RenewalService s = verifiedCall();
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "", 1), "voice"),
                HttpStatus.UNPROCESSABLE_ENTITY, "OUTSIDE_PLAYBOOK");
        assertThat(callRow.getOutOfPlaybookRequests()).isEqualTo(1);
        assertThat(actions()).contains("rule.outside_playbook");
    }

    @Test
    void secondOutOfPlaybookRequestForcesHandoff() {
        RenewalService s = verifiedCall();
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "annual", 10), "voice"),
                HttpStatus.UNPROCESSABLE_ENTITY, "OUTSIDE_PLAYBOOK");
        assertThat(callRow.getOutOfPlaybookRequests()).isEqualTo(1);
        assertThat(callRow.isMustHandoff()).isFalse();
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "annual", 5), "voice"),
                HttpStatus.UNPROCESSABLE_ENTITY, "OUTSIDE_PLAYBOOK");
        assertThat(callRow.getOutOfPlaybookRequests()).isEqualTo(2);
        assertThat(callRow.isMustHandoff()).isTrue();
        assertThat(actions().stream().filter("rule.outside_playbook"::equals)).hasSize(2);
        assertThat(callRow.getLastQuote()).isNull();
    }

    @Test
    void quoteRefusedAfterForcedHandoff() {
        RenewalService s = verifiedCall();
        for (int i = 0; i < 2; i++) {
            assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "annual", 10), "voice"),
                    HttpStatus.UNPROCESSABLE_ENTITY, "OUTSIDE_PLAYBOOK");
        }
        assertThat(callRow.isMustHandoff()).isTrue();
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "annual", 0), "voice"),
                HttpStatus.CONFLICT, "MUST_HANDOFF");
        assertRefused(() -> s.options(id(), "voice"), HttpStatus.CONFLICT, "MUST_HANDOFF");
        assertThat(callRow.getLastQuote()).isNull();
        s.turn(id(), new TurnRequest("customer", "ok", "t"), "voice");
        assertThat(s.handoff(id(), new HandoffRequest("limit reached", null), "voice").queued()).isTrue();
        assertThat(s.end(id(), "voice").outcome()).isEqualTo("HANDED_OFF");
        assertThat(s.getCall(id()).mustHandoff()).isTrue();
    }

    @Test
    void paymentLinkRefusedAfterForcedHandoff() {
        RenewalService s = verifiedCall();
        Quote q = s.quote(id(), new QuoteRequest(List.of(), "annual", 0), "voice");
        for (int i = 0; i < 2; i++) {
            assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "annual", 10), "voice"),
                    HttpStatus.UNPROCESSABLE_ENTITY, "OUTSIDE_PLAYBOOK");
        }
        assertRefused(() -> s.paymentLink(id(), q.quoteId(), "voice"), HttpStatus.CONFLICT, "MUST_HANDOFF");
        assertThat(callRow.isPaymentLinkSent()).isFalse();
    }

    private boolean refusedWith(String code) {
        return events.stream().anyMatch(e -> e.action().equals("tool.refused")
                && e.payload().path("code").asText().equals(code));
    }

    @Test
    void policyBeforeVerifyIsAudited() {
        RenewalService s = startedCall();
        assertRefused(() -> s.policy(id(), "voice"), HttpStatus.FORBIDDEN, "IDENTITY_NOT_VERIFIED");
        assertThat(refusedWith("IDENTITY_NOT_VERIFIED")).isTrue();
        assertThat(events.get(events.size() - 1).payload().path("tool").asText()).isEqualTo("get_policy");
    }

    @Test
    void refusedQuoteAfterForcedHandoffIsAudited() {
        RenewalService s = verifiedCall();
        for (int i = 0; i < 2; i++) {
            assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "annual", 10), "voice"),
                    HttpStatus.UNPROCESSABLE_ENTITY, "OUTSIDE_PLAYBOOK");
        }
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "annual", 0), "voice"),
                HttpStatus.CONFLICT, "MUST_HANDOFF");
        assertThat(refusedWith("MUST_HANDOFF")).isTrue();
    }

    @Test
    void otherRefusalsAreAudited() {
        RenewalService s = verifiedCall();
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of("BASE"), "annual", 0), "voice"),
                HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_OPTION");
        assertRefused(() -> s.paymentLink(id(), UUID.randomUUID(), "voice"), HttpStatus.CONFLICT, "STALE_QUOTE");
        s.verify(id(), "1980-03-14", "voice");
        assertThat(refusedWith("INVALID_OPTION") && refusedWith("STALE_QUOTE") && refusedWith("ALREADY_VERIFIED"))
                .isTrue();
        s.end(id(), "voice");
        assertRefused(() -> s.policy(id(), "voice"), HttpStatus.CONFLICT, "CALL_ENDED");
        assertThat(refusedWith("CALL_ENDED")).isTrue();
    }

    @Test
    void lockedVerifyIsAudited() {
        RenewalService s = startedCall();
        for (int i = 0; i < 3; i++) {
            s.verify(id(), "1999-01-0" + (i + 1), "voice");
        }
        assertRefused(() -> s.verify(id(), "1980-03-14", "voice"), HttpStatus.CONFLICT, "VERIFY_LOCKED");
        assertThat(refusedWith("VERIFY_LOCKED")).isTrue();
    }

    @Test
    void quoteAfterVoluntaryHandoffIsRefused() {
        RenewalService s = verifiedCall();
        s.handoff(id(), new HandoffRequest("Customer wants a person", null), "voice");
        assertThat(callRow.isMustHandoff()).isTrue();
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "annual", 0), "voice"),
                HttpStatus.CONFLICT, "MUST_HANDOFF");
        assertRefused(() -> s.paymentLink(id(), UUID.randomUUID(), "voice"), HttpStatus.CONFLICT, "MUST_HANDOFF");
        assertThat(callRow.isPaymentLinkSent()).isFalse();
    }

    @Test
    void paymentLinkNeedsLatestQuote() {
        RenewalService s = verifiedCall();
        Quote first = s.quote(id(), new QuoteRequest(List.of("OPD"), "quarterly", 0), "voice");
        Quote second = s.quote(id(), new QuoteRequest(List.of(), "annual", 0), "voice");
        assertRefused(() -> s.paymentLink(id(), first.quoteId(), "voice"), HttpStatus.CONFLICT, "STALE_QUOTE");
        assertThat(callRow.isPaymentLinkSent()).isFalse();
        var sent = s.paymentLink(id(), second.quoteId(), "voice");
        assertThat(sent.sent()).isTrue();
        assertThat(sent.channel()).isEqualTo("SMS");
        assertThat(sent.mobileLast4()).isEqualTo("4821");
        assertThat(callRow.isPaymentLinkSent()).isTrue();
        assertThat(actions()).contains("tool.send_payment_link");
    }

    @Test
    void endOutcomes() {
        RenewalService paid = verifiedCall();
        paid.paymentLink(id(), paid.quote(id(), new QuoteRequest(List.of(), "annual", 0), "voice").quoteId(), "voice");
        assertThat(paid.end(id(), "voice").outcome()).isEqualTo("RENEWAL_PENDING_PAYMENT");
        assertThat(caseRow.getStatus()).isEqualTo(CaseStatus.NEEDS_REVIEW);
        assertThat(callRow.getEndedAt()).isNotNull();

        RenewalService none = startedCall();
        assertThat(none.end(id(), "voice").outcome()).isEqualTo("NO_DECISION");
        assertThat(caseRow.getStatus()).isEqualTo(CaseStatus.NEEDS_REVIEW);

        RenewalService handed = startedCall();
        assertThat(handed.handoff(id(), new HandoffRequest("Customer wants a manager", "2026-10-30T10:00:00+05:30"),
                "voice").queued()).isTrue();
        assertThat(caseRow.getStatus()).isEqualTo(CaseStatus.ESCALATED);
        assertThat(handed.end(id(), "voice").outcome()).isEqualTo("HANDED_OFF");
        assertThat(caseRow.getStatus()).isEqualTo(CaseStatus.ESCALATED);
        assertThat(handed.end(id(), "voice").outcome()).isEqualTo("HANDED_OFF");
        assertThat(actions().stream().filter("call.ended"::equals)).hasSize(3);
    }

    @Test
    void toolsAfterEndAreRefused() {
        RenewalService s = verifiedCall();
        s.end(id(), "voice");
        assertRefused(() -> s.policy(id(), "voice"), HttpStatus.CONFLICT, "CALL_ENDED");
        assertRefused(() -> s.verify(id(), "1980-03-14", "voice"), HttpStatus.CONFLICT, "CALL_ENDED");
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "annual", 0), "voice"),
                HttpStatus.CONFLICT, "CALL_ENDED");
        assertRefused(() -> s.handoff(id(), new HandoffRequest("x", null), "voice"), HttpStatus.CONFLICT, "CALL_ENDED");
        assertRefused(() -> s.turn(id(), new TurnRequest("agent", "hi", "t"), "voice"),
                HttpStatus.CONFLICT, "CALL_ENDED");
    }

    @Test
    void summaryQuotesPrecedingCustomerTurn() {
        RenewalService s = verifiedCall();
        s.turn(id(), new TurnRequest("agent", "Your premium is 18450.", "2026-10-29T11:00:01+05:30"), "voice");
        s.turn(id(), new TurnRequest("customer", "Can you give me a discount?", "2026-10-29T11:00:05+05:30"), "voice");
        s.turn(id(), new TurnRequest("agent", "Let me check.", "2026-10-29T11:00:06+05:30"), "voice");
        assertRefused(() -> s.quote(id(), new QuoteRequest(List.of(), "annual", 10), "voice"),
                HttpStatus.UNPROCESSABLE_ENTITY, "OUTSIDE_PLAYBOOK");
        s.turn(id(), new TurnRequest("customer", "Drop the outpatient cover, pay quarterly.", "t"), "voice");
        Quote q = s.quote(id(), new QuoteRequest(List.of("OPD"), "quarterly", 0), "voice");
        s.turn(id(), new TurnRequest("customer", "Send me the link.", "t"), "voice");
        s.paymentLink(id(), q.quoteId(), "voice");

        CallView v = s.getCall(id());
        assertThat(v.summary()).extracting(RenewalDtos.SummaryItem::statement).containsExactly(
                "Customer asked for a discount beyond the playbook limit.",
                "Agent quoted a renewal option within the playbook.",
                "Payment link sent to the customer's registered mobile.");
        assertThat(v.summary()).extracting(RenewalDtos.SummaryItem::quote).containsExactly(
                "Can you give me a discount?", "Drop the outpatient cover, pay quarterly.", "Send me the link.");
        assertThat(v.transcript()).hasSize(5);
        assertThat(v.holderName()).isEqualTo("Meera Iyer");
        assertThat(v.greeting()).contains("Meera Iyer").doesNotContain("{holderName}");
        assertThat(v.identityVerified()).isTrue();
        assertThat(v.paymentLinkSent()).isTrue();
        assertThat(v.outOfPlaybookRequests()).isEqualTo(1);
        JsonNode lq = v.lastQuote();
        assertThat(lq.get("annualPremium").asInt()).isEqualTo(16350);
        assertThat(actions()).doesNotContain("call.turn");
    }

    @Test
    void turnRejectsBadRoleAndEmptyText() {
        RenewalService s = startedCall();
        assertThatThrownBy(() -> s.turn(id(), new TurnRequest("robot", "hi", "t"), "voice"))
                .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.status()).isEqualTo(HttpStatus.BAD_REQUEST));
        assertThatThrownBy(() -> s.turn(id(), new TurnRequest("agent", " ", "t"), "voice"))
                .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.status()).isEqualTo(HttpStatus.BAD_REQUEST));
    }

    private static void assertConflict(Runnable r, String detail) {
        assertThatThrownBy(r::run).isInstanceOfSatisfying(ApiException.class, e -> {
            assertThat(e.status()).isEqualTo(HttpStatus.CONFLICT);
            assertThat(e.getMessage()).isEqualTo(detail);
        });
    }
}
