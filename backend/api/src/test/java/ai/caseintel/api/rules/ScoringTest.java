package ai.caseintel.api.rules;

import static org.assertj.core.api.Assertions.assertThat;

import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.domain.FindingSource;
import ai.caseintel.api.domain.Severity;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;

class ScoringTest {

    private static final PackConfig.Routing ROUTING = new PackConfig.Routing(0.2, 0.8);

    @Test
    void scoreIsWeightTimesSeverityFactor() {
        var findings = List.of(
                new Scoring.Weighted(0.3, Severity.MEDIUM, FindingSource.RULE),   // 0.18
                new Scoring.Weighted(0.5, Severity.LOW, FindingSource.RULE));     // 0.15
        assertThat(Scoring.score(findings)).isEqualByComparingTo("0.330");
    }

    @Test
    void scoreIsCappedAtOne() {
        var findings = List.of(
                new Scoring.Weighted(0.8, Severity.HIGH, FindingSource.SECURITY),
                new Scoring.Weighted(0.6, Severity.HIGH, FindingSource.SECURITY));
        assertThat(Scoring.score(findings)).isEqualByComparingTo("1.000");
    }

    @Test
    void noFindingsScoresZeroAndAutoClears() {
        BigDecimal score = Scoring.score(List.of());
        assertThat(score).isEqualByComparingTo("0");
        assertThat(Scoring.route(score, ROUTING, List.of())).isEqualTo(CaseStatus.AUTO_CLEARED);
    }

    @Test
    void routesByThresholdsWithInclusiveEscalation() {
        assertThat(Scoring.route(new BigDecimal("0.199"), ROUTING, List.of())).isEqualTo(CaseStatus.AUTO_CLEARED);
        assertThat(Scoring.route(new BigDecimal("0.200"), ROUTING, List.of())).isEqualTo(CaseStatus.NEEDS_REVIEW);
        assertThat(Scoring.route(new BigDecimal("0.799"), ROUTING, List.of())).isEqualTo(CaseStatus.NEEDS_REVIEW);
        assertThat(Scoring.route(new BigDecimal("0.800"), ROUTING, List.of())).isEqualTo(CaseStatus.ESCALATED);
    }

    @Test
    void securityFindingNeverAutoClears() {
        var lowSecurity = List.of(new Scoring.Weighted(0.1, Severity.LOW, FindingSource.SECURITY));
        BigDecimal score = Scoring.score(lowSecurity);
        assertThat(score).isEqualByComparingTo("0.030");
        assertThat(Scoring.route(score, ROUTING, lowSecurity)).isEqualTo(CaseStatus.NEEDS_REVIEW);
    }
}
