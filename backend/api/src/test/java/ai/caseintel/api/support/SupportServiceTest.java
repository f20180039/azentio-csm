package ai.caseintel.api.support;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.config.AppProperties;
import ai.caseintel.api.domain.CaseEntity;
import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.renewals.CallEntity;
import ai.caseintel.api.renewals.CallRepository;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.service.ApiException;
import ai.caseintel.api.support.SupportDtos.CallDetail;
import ai.caseintel.api.support.SupportDtos.CallSummary;
import ai.caseintel.api.support.SupportDtos.TurnRequest;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;

class SupportServiceTest {

    private final CallRepository calls = mock(CallRepository.class);
    private final CaseRepository cases = mock(CaseRepository.class);
    private final AuditService audit = mock(AuditService.class);
    private final ObjectMapper mapper = new ObjectMapper();
    private final Clock clock = Clock.fixed(Instant.parse("2026-10-31T06:00:00Z"), ZoneOffset.UTC);
    private final SupportService service = new SupportService(calls, cases, audit, clock,
            new AppProperties("test", null, null, null, null, null, null, null), mapper);
    private CallEntity callRow;
    private CaseEntity caseRow;

    @BeforeEach
    void setUp() {
        when(calls.save(any())).thenAnswer(i -> callRow = i.getArgument(0));
        when(cases.save(any())).thenAnswer(i -> caseRow = i.getArgument(0));
        when(calls.findForUpdate(any())).thenAnswer(i -> Optional.ofNullable(callRow));
        when(calls.findById(any())).thenAnswer(i -> Optional.ofNullable(callRow));
        when(cases.findById(any())).thenAnswer(i -> Optional.ofNullable(caseRow));
    }

    private TurnRequest turn(String role, String text, String meta) throws Exception {
        return new TurnRequest(role, text, null, meta == null ? null : mapper.readTree(meta));
    }

    @Test
    void startCreatesSupportCallAndCaseAndAudits() {
        UUID id = service.start(Channel.VOICE, "voice").id();

        assertThat(callRow.getKind()).isEqualTo(CallKind.SUPPORT);
        assertThat(callRow.getChannel()).isEqualTo(Channel.VOICE);
        assertThat(callRow.getPolicyId()).isNull();
        assertThat(caseRow.getCaseType()).isEqualTo("support_call");
        assertThat(caseRow.getStatus()).isEqualTo(CaseStatus.PROCESSING);
        verify(audit).record(eq(id), eq("voice"), eq("call.started"), anyMap());
    }

    @Test
    void turnsKeepOrderMetaMergesAndSummaryDerivesFromCustomerTurns() throws Exception {
        UUID id = service.start(Channel.TEXT, "voice").id();
        service.addTurn(id, turn("customer", "EMI date?", "{\"intents\":[\"REPAYMENT\"],\"verified\":true}"), "voice");
        service.addTurn(id, turn("agent", "The 5th.", "{\"tool_trace\":[{\"name\":\"get_loan\"}],"
                + "\"intents\":[\"IGNORED_ON_AGENT\"],\"verified\":false}"), "voice");
        service.addTurn(id, turn("customer", "And my card?", "{\"intents\":[\"CARD_BLOCK\",\"REPAYMENT\"]}"), "voice");
        service.addTurn(id, turn("customer", "Thanks", null), "voice");

        service.patchMeta(id, 1, mapper.readTree("{\"intent_source\":\"rules\",\"verified\":true}"));
        service.patchMeta(id, 1, mapper.readTree("{\"intent_source\":\"llm\"}"));

        CallDetail d = service.get(id);
        assertThat(d.turns()).extracting(SupportDtos.Turn::seq).containsExactly(1, 2, 3, 4);
        assertThat(d.turns().get(0).meta().path("intent_source").asText()).isEqualTo("llm");
        assertThat(d.turns().get(0).meta().path("intents").get(0).asText()).isEqualTo("REPAYMENT");
        assertThat(d.turns().get(0).at()).isEqualTo("2026-10-31T06:00:00Z");
        assertThat(d.turns().get(3).meta().isObject()).isTrue();
        assertThat(d.verified()).isTrue();

        List<String> intents = SupportService.intents((com.fasterxml.jackson.databind.node.ArrayNode)
                mapper.readTree(callRow.getTranscript()));
        assertThat(intents).containsExactly("REPAYMENT", "CARD_BLOCK");
    }

    @Test
    void verifiedOnlyCountsCustomerTurns() throws Exception {
        UUID id = service.start(Channel.TEXT, "voice").id();
        service.addTurn(id, turn("agent", "Verified you.", "{\"verified\":true}"), "voice");
        service.addTurn(id, turn("customer", "ok", "{\"verified\":false}"), "voice");
        assertThat(service.get(id).verified()).isFalse();
    }

    @Test
    void endSetsOutcomeCaseStatusAndRejectsSecondEndAndLateTurns() throws Exception {
        UUID id = service.start(Channel.SIM_AUDIO, "voice").id();
        service.addTurn(id, turn("customer", "I want to complain", null), "voice");

        service.end(id, Outcome.ESCALATED, "voice");

        assertThat(callRow.getOutcome()).isEqualTo("ESCALATED");
        assertThat(callRow.getEndedAt()).isEqualTo(clock.instant());
        assertThat(caseRow.getStatus()).isEqualTo(CaseStatus.ESCALATED);
        verify(audit).record(id, "voice", "call.ended", java.util.Map.of("outcome", "ESCALATED", "turnCount", 1));
        assertThatThrownBy(() -> service.end(id, Outcome.RESOLVED, "voice"))
                .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.status()).isEqualTo(HttpStatus.CONFLICT));
        assertThatThrownBy(() -> service.addTurn(id, turn("agent", "late", null), "voice"))
                .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.status()).isEqualTo(HttpStatus.CONFLICT));
        // intents are back-filled after the classifier finishes, which can be after the call ends
        service.patchMeta(id, 1, mapper.readTree("{\"intents\":[\"COMPLAINT\"]}"));
        assertThat(service.get(id).turns().get(0).meta().path("intents").get(0).asText()).isEqualTo("COMPLAINT");
    }

    @Test
    void listQueriesSupportNewestFirstAndSummarises() throws Exception {
        UUID id = service.start(Channel.VOICE, "voice").id();
        service.addTurn(id, turn("customer", "EMI?", "{\"intents\":[\"REPAYMENT\"],\"verified\":true}"), "voice");
        service.end(id, Outcome.TICKET_CREATED, "voice");
        when(calls.findByKindAndOutcome(eq(CallKind.SUPPORT), eq("TICKET_CREATED"), any()))
                .thenReturn(List.of(callRow));

        List<CallSummary> items = service.list(Outcome.TICKET_CREATED, 10).items();

        assertThat(items).singleElement().satisfies(s -> {
            assertThat(s.turnCount()).isEqualTo(1);
            assertThat(s.verified()).isTrue();
            assertThat(s.intents()).containsExactly("REPAYMENT");
            assertThat(s.outcome()).isEqualTo(Outcome.TICKET_CREATED);
        });
        ArgumentCaptor<Pageable> page = ArgumentCaptor.forClass(Pageable.class);
        verify(calls).findByKindAndOutcome(eq(CallKind.SUPPORT), eq("TICKET_CREATED"), page.capture());
        assertThat(page.getValue().getPageSize()).isEqualTo(10);
        assertThat(page.getValue().getSort().getOrderFor("startedAt").getDirection()).isEqualTo(Sort.Direction.DESC);
        assertThatThrownBy(() -> service.list(null, 0)).isInstanceOf(ApiException.class);
    }

    @Test
    void vocabulariesRejectUnknownValues() {
        assertThatThrownBy(() -> Outcome.parse("HANDED_OFF")).isInstanceOfSatisfying(ApiException.class, e -> {
            assertThat(e.status()).isEqualTo(HttpStatus.BAD_REQUEST);
            assertThat(e.getMessage()).contains("RESOLVED").contains("HANDED_OFF");
        });
        assertThatThrownBy(() -> Channel.parse(null)).isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> TurnRole.parse("Customer")).isInstanceOf(ApiException.class);
        assertThat(Outcome.parse("ROUTED")).isEqualTo(Outcome.ROUTED);
    }
}
