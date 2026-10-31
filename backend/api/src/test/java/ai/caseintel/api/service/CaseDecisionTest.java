package ai.caseintel.api.service;

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
import ai.caseintel.api.jobs.JobQueue;
import ai.caseintel.api.repo.CaseRepository;
import ai.caseintel.api.repo.DocumentRepository;
import ai.caseintel.api.repo.ExtractionRepository;
import ai.caseintel.api.repo.FindingRepository;
import ai.caseintel.api.rules.PackRegistry;
import ai.caseintel.api.storage.FileStorage;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

class CaseDecisionTest {

    private final CaseRepository cases = mock(CaseRepository.class);
    private final AuditService audit = mock(AuditService.class);
    private CaseService service;
    private CaseEntity c;

    @BeforeEach
    void setUp() {
        service = new CaseService(cases, mock(DocumentRepository.class), mock(ExtractionRepository.class),
                mock(FindingRepository.class), mock(PackRegistry.class), mock(JobQueue.class), mock(FileStorage.class),
                audit, mock(UploadRateLimiter.class), new ProcessingMetrics(), new ObjectMapper(),
                mock(AppProperties.class));
        c = new CaseEntity(UUID.randomUUID(), "demo", "t", "v1", "analyst", Instant.now());
        c.setStatus(CaseStatus.NEEDS_REVIEW);
        when(cases.findById(c.getId())).thenReturn(Optional.of(c));
    }

    @Test
    void uploaderCannotDecideTheirOwnCase() {
        assertThatThrownBy(() -> service.decideCase(c.getId(), new Dtos.CaseDecision("APPROVE", "looks fine"), "analyst"))
                .isInstanceOfSatisfying(ApiException.class, e -> {
                    assertThat(e.status()).isEqualTo(HttpStatus.FORBIDDEN);
                    assertThat(e.getMessage()).contains("Four-eyes");
                });
        assertThat(c.getStatus()).isEqualTo(CaseStatus.NEEDS_REVIEW);
        verify(audit, never()).record(any(), any(), any(), any());
    }

    @Test
    void anotherReviewerCanDecideAndTheDecisionIsAudited() {
        var detail = service.decideCase(c.getId(), new Dtos.CaseDecision("approve", "Evidence checked"), "reviewer");
        assertThat(c.getStatus()).isEqualTo(CaseStatus.APPROVED);
        assertThat(detail.status()).isEqualTo(CaseStatus.APPROVED);
        verify(audit).record(eq(c.getId()), eq("reviewer"), eq("CASE_APPROVE"), anyMap());
    }

    @Test
    void decisionNeedsAReason() {
        assertThatThrownBy(() -> service.decideCase(c.getId(), new Dtos.CaseDecision("REJECT", " "), "reviewer"))
                .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.status()).isEqualTo(HttpStatus.BAD_REQUEST));
    }

    @Test
    void cannotDecideWhileStillProcessing() {
        c.setStatus(CaseStatus.PROCESSING);
        assertThatThrownBy(() -> service.decideCase(c.getId(), new Dtos.CaseDecision("APPROVE", "ok"), "reviewer"))
                .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.status()).isEqualTo(HttpStatus.CONFLICT));
    }

    @Test
    void unknownActionIsRejected() {
        assertThatThrownBy(() -> service.decideCase(c.getId(), new Dtos.CaseDecision("DELETE", "x"), "reviewer"))
                .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.status()).isEqualTo(HttpStatus.BAD_REQUEST));
    }

    @Test
    void pdfMagicIsDetected() {
        assertThat(CaseService.isPdf("%PDF-1.7\n".getBytes())).isTrue();
        assertThat(CaseService.isPdf("hello".getBytes())).isFalse();
    }

    @Test
    void attributesMustBeASmallJsonObject() {
        assertThat(service.parseAttributes(null).isObject()).isTrue();
        assertThat(service.parseAttributes(" ").size()).isZero();
        assertThat(service.parseAttributes("{\"policyNo\":\"POL-1\",\"income\":{\"declared\":85000}}")
                .path("income").path("declared").asInt()).isEqualTo(85000);

        for (String bad : new String[] {"[1,2]", "\"x\"", "{oops", "{\"a\":\"" + "x".repeat(9000) + "\"}"}) {
            assertThatThrownBy(() -> service.parseAttributes(bad))
                    .isInstanceOfSatisfying(ApiException.class, e -> assertThat(e.status()).isEqualTo(HttpStatus.BAD_REQUEST));
        }
    }
}
