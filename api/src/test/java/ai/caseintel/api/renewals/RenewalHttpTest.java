package ai.caseintel.api.renewals;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.httpBasic;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.config.AppProperties;
import ai.caseintel.api.config.SecurityConfig;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.web.ApiExceptionHandler;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
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

/** Real security chain and real RenewalService (so its @PreAuthorize applies); only storage is mocked. */
@WebMvcTest(RenewalController.class)
@Import({SecurityConfig.class, ApiExceptionHandler.class, RenewalService.class, RenewalHttpTest.Beans.class})
@EnableConfigurationProperties(AppProperties.class)
@TestPropertySource(properties = {"app.cors.allowed-origins=http://localhost",
        "app.renewals.enforce-calling-hours=false", "app.renewals.playbook=playbooks/health-renewal.yml"})
class RenewalHttpTest {

    @TestConfiguration
    static class Beans {
        @Bean
        Clock clock() {
            return Clock.fixed(Instant.parse("2026-10-29T06:00:00Z"), ZoneOffset.UTC);
        }

        @Bean
        Playbook playbook() {
            return PlaybookLoader.load("playbooks/health-renewal.yml");
        }

        @Bean
        com.fasterxml.jackson.databind.ObjectMapper mapper() {
            return new com.fasterxml.jackson.databind.ObjectMapper();
        }
    }

    @MockBean PolicyRepository policies;
    @MockBean CallRepository calls;
    @MockBean CaseRepository cases;
    @MockBean AuditService audit;
    @Autowired MockMvc mvc;

    private final UUID callId = UUID.randomUUID();

    private CallEntity openCall() {
        CallEntity c = new CallEntity(callId, "HF-2291-0457", Instant.now());
        when(calls.findForUpdate(any())).thenReturn(Optional.of(c));
        return c;
    }

    @Test
    void voiceCanVerify() throws Exception {
        PolicyEntity p = PolicyFixtures.with(PolicyFixtures.meera(), "dateOfBirth", java.time.LocalDate.of(1980, 3, 14));
        when(policies.findById("HF-2291-0457")).thenReturn(Optional.of(p));
        openCall();
        mvc.perform(post("/api/v1/renewals/calls/{id}/verify", callId).with(httpBasic("voice", "voice"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"dateOfBirth\":\"1980-03-14\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.verified").value(true))
                .andExpect(jsonPath("$.mustHandoff").value(false));
    }

    @Test
    void voiceCannotUseAnalystEndpoints() throws Exception {
        mvc.perform(get("/api/v1/renewals/queue").with(httpBasic("voice", "voice"))).andExpect(status().isForbidden());
        mvc.perform(post("/api/v1/renewals/calls").with(httpBasic("voice", "voice"))
                        .contentType(MediaType.APPLICATION_JSON).content("{\"policyId\":\"HF-2291-0457\"}"))
                .andExpect(status().isForbidden());
    }

    @Test
    void analystCanReadCallButAnonymousCannot() throws Exception {
        when(calls.findById(any())).thenReturn(Optional.empty());
        mvc.perform(get("/api/v1/renewals/calls/{id}", callId).with(httpBasic("analyst", "analyst")))
                .andExpect(status().isNotFound());
        mvc.perform(get("/api/v1/renewals/calls/{id}", callId).with(httpBasic("voice", "voice")))
                .andExpect(status().isNotFound());
        mvc.perform(get("/api/v1/renewals/calls/{id}", callId)).andExpect(status().isUnauthorized());
    }

    @Test
    void refusalIsProblemJsonWithCodeAsDetail() throws Exception {
        openCall();
        mvc.perform(get("/api/v1/renewals/calls/{id}/policy", callId).with(httpBasic("voice", "voice")))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.detail").value("IDENTITY_NOT_VERIFIED"));
    }
}
