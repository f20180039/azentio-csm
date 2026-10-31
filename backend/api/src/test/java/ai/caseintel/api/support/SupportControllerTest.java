package ai.caseintel.api.support;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.httpBasic;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.config.AppProperties;
import ai.caseintel.api.config.SecurityConfig;
import ai.caseintel.api.renewals.CallEntity;
import ai.caseintel.api.renewals.CallRepository;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.web.ApiExceptionHandler;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

/** Real security chain and real SupportService; the calls table is an in-memory list behind a mocked repository. */
@WebMvcTest(SupportController.class)
@Import({SecurityConfig.class, ApiExceptionHandler.class, SupportService.class, SupportControllerTest.Beans.class})
@EnableConfigurationProperties(AppProperties.class)
@TestPropertySource(properties = {"app.cors.allowed-origins=http://localhost",
        "app.renewals.playbook=playbooks/health-renewal.yml"})
class SupportControllerTest {

    @TestConfiguration
    static class Beans {
        @Bean
        Clock clock() {
            return Clock.fixed(Instant.parse("2026-10-31T06:00:00Z"), ZoneOffset.UTC);
        }
    }

    @MockBean CallRepository calls;
    @MockBean CaseRepository cases;
    @MockBean AuditService audit;
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;

    private final List<CallEntity> rows = new ArrayList<>();

    @BeforeEach
    void storage() {
        when(calls.save(any())).thenAnswer(i -> {
            CallEntity c = i.getArgument(0);
            rows.removeIf(r -> r.getId().equals(c.getId()));
            rows.add(c);
            return c;
        });
        when(calls.findForUpdate(any())).thenAnswer(i -> find(i.getArgument(0)));
        when(calls.findById(any())).thenAnswer(i -> find(i.getArgument(0)));
        when(calls.findByKind(eq(CallKind.SUPPORT), any())).thenAnswer(i -> newestFirst(null));
        when(calls.findByKindAndOutcome(eq(CallKind.SUPPORT), any(), any()))
                .thenAnswer(i -> newestFirst(i.getArgument(1)));
    }

    private Optional<CallEntity> find(UUID id) {
        return rows.stream().filter(r -> r.getId().equals(id)).findFirst();
    }

    private List<CallEntity> newestFirst(String outcome) {
        return rows.stream().filter(r -> r.getKind() == CallKind.SUPPORT)
                .filter(r -> outcome == null || outcome.equals(r.getOutcome()))
                .sorted((a, b) -> b.getStartedAt().compareTo(a.getStartedAt())).toList();
    }

    private String start() throws Exception {
        String body = mvc.perform(post("/api/v1/support/calls").with(httpBasic("voice", "voice"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"channel\":\"SIM_AUDIO\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").isNotEmpty())
                .andReturn().getResponse().getContentAsString();
        return mapper.readTree(body).path("id").asText();
    }

    private void end(String id, String outcome, int expected) throws Exception {
        mvc.perform(post("/api/v1/support/calls/{id}/end", id).with(httpBasic("voice", "voice"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"outcome\":\"" + outcome + "\"}"))
                .andExpect(status().is(expected));
    }

    @Test
    void fullCallRoundTripWithMergedMetaAndListing() throws Exception {
        String id = start();

        mvc.perform(post("/api/v1/support/calls/{id}/turns", id).with(httpBasic("voice", "voice"))
                        .contentType(MediaType.APPLICATION_JSON).content("""
                                {"role":"customer","text":"When is my EMI due?","at":"2026-10-31T06:00:01Z",
                                 "meta":{"intents":["REPAYMENT"],"verified":true}}"""))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.seq").value(1));
        mvc.perform(post("/api/v1/support/calls/{id}/turns", id).with(httpBasic("voice", "voice"))
                        .contentType(MediaType.APPLICATION_JSON).content("""
                                {"role":"agent","text":"Your next EMI is due on the 5th.","at":"2026-10-31T06:00:03Z",
                                 "meta":{"tool_trace":[{"name":"get_loan","args":{"loan_id":"LN-1"},
                                         "result_summary":"next_due 2026-11-05"}],
                                         "retrieved":{"get_loan":{"next_due":"2026-11-05"}},"refs":[]}}"""))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.seq").value(2));

        mvc.perform(patch("/api/v1/support/calls/{id}/turns/{seq}/meta", id, 1).with(httpBasic("voice", "voice"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"intent_source\":\"llm\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.meta.intent_source").value("llm"))
                .andExpect(jsonPath("$.meta.verified").value(true));

        end(id, "TICKET_CREATED", 200);

        mvc.perform(get("/api/v1/support/calls/{id}", id).with(httpBasic("analyst", "analyst")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(id))
                .andExpect(jsonPath("$.channel").value("SIM_AUDIO"))
                .andExpect(jsonPath("$.startedAt").value("2026-10-31T06:00:00Z"))
                .andExpect(jsonPath("$.endedAt").value("2026-10-31T06:00:00Z"))
                .andExpect(jsonPath("$.outcome").value("TICKET_CREATED"))
                .andExpect(jsonPath("$.verified").value(true))
                .andExpect(jsonPath("$.turns.length()").value(2))
                .andExpect(jsonPath("$.turns[0].seq").value(1))
                .andExpect(jsonPath("$.turns[0].role").value("customer"))
                .andExpect(jsonPath("$.turns[0].at").value("2026-10-31T06:00:01Z"))
                .andExpect(jsonPath("$.turns[0].meta.intents[0]").value("REPAYMENT"))
                .andExpect(jsonPath("$.turns[0].meta.verified").value(true))
                .andExpect(jsonPath("$.turns[0].meta.intent_source").value("llm"))
                .andExpect(jsonPath("$.turns[1].seq").value(2))
                .andExpect(jsonPath("$.turns[1].role").value("agent"))
                .andExpect(jsonPath("$.turns[1].meta.tool_trace[0].name").value("get_loan"))
                .andExpect(jsonPath("$.turns[1].meta.tool_trace[0].result_summary").value("next_due 2026-11-05"))
                .andExpect(jsonPath("$.turns[1].meta.retrieved.get_loan.next_due").value("2026-11-05"));

        mvc.perform(get("/api/v1/support/calls").param("outcome", "TICKET_CREATED").param("limit", "50")
                        .with(httpBasic("reviewer", "reviewer")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(1))
                .andExpect(jsonPath("$.items[0].id").value(id))
                .andExpect(jsonPath("$.items[0].outcome").value("TICKET_CREATED"))
                .andExpect(jsonPath("$.items[0].verified").value(true))
                .andExpect(jsonPath("$.items[0].turnCount").value(2))
                .andExpect(jsonPath("$.items[0].intents.length()").value(1))
                .andExpect(jsonPath("$.items[0].intents[0]").value("REPAYMENT"));
        mvc.perform(get("/api/v1/support/calls").param("outcome", "RESOLVED").with(httpBasic("admin", "admin")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(0));

        UUID callId = UUID.fromString(id);
        verify(audit).record(eq(callId), eq("voice"), eq("call.started"), anyMap());
        verify(audit).record(eq(callId), eq("voice"), eq("call.ended"),
                eq(java.util.Map.of("outcome", "TICKET_CREATED", "turnCount", 2)));
    }

    @Test
    void unknownOutcomeIsRejectedAndCallStaysOpen() throws Exception {
        String id = start();
        mvc.perform(post("/api/v1/support/calls/{id}/end", id).with(httpBasic("voice", "voice"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"outcome\":\"HANDED_OFF\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.detail").value(org.hamcrest.Matchers.startsWith("outcome must be one of")));
        assertThat(find(UUID.fromString(id)).orElseThrow().getEndedAt()).isNull();
        mvc.perform(get("/api/v1/support/calls").param("outcome", "NOPE").with(httpBasic("analyst", "analyst")))
                .andExpect(status().isBadRequest());
    }

    @Test
    void unknownChannelAndRoleAreRejected() throws Exception {
        mvc.perform(post("/api/v1/support/calls").with(httpBasic("voice", "voice"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"channel\":\"FAX\"}"))
                .andExpect(status().isBadRequest());
        String id = start();
        mvc.perform(post("/api/v1/support/calls/{id}/turns", id).with(httpBasic("voice", "voice"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"role\":\"bot\",\"text\":\"hi\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void endingTwiceIs409() throws Exception {
        String id = start();
        end(id, "RESOLVED", 200);
        end(id, "ESCALATED", 409);
        assertThat(find(UUID.fromString(id)).orElseThrow().getOutcome()).isEqualTo("RESOLVED");
    }

    @Test
    void patchOnMissingTurnIs404() throws Exception {
        String id = start();
        mvc.perform(patch("/api/v1/support/calls/{id}/turns/{seq}/meta", id, 1).with(httpBasic("voice", "voice"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"intents\":[\"KYC\"]}"))
                .andExpect(status().isNotFound());
    }

    @Test
    void onlyVoiceWritesAndStaffRead() throws Exception {
        mvc.perform(post("/api/v1/support/calls").with(httpBasic("analyst", "analyst"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"channel\":\"VOICE\"}"))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/v1/support/calls")).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/v1/support/calls").with(httpBasic("analyst", "analyst"))).andExpect(status().isOk());
        verify(cases, never()).save(any());
    }

    @Test
    void renewalCallIsNotASupportCall() throws Exception {
        CallEntity renewal = new CallEntity(UUID.randomUUID(), "HF-2291-0457", Instant.now());
        rows.add(renewal);
        mvc.perform(get("/api/v1/support/calls/{id}", renewal.getId()).with(httpBasic("analyst", "analyst")))
                .andExpect(status().isNotFound());
        mvc.perform(get("/api/v1/support/calls").with(httpBasic("analyst", "analyst")))
                .andExpect(jsonPath("$.items.length()").value(0));
    }
}
