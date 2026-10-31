package ai.caseintel.api.rules;

import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.domain.FindingSource;
import ai.caseintel.api.domain.Severity;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.List;

public final class Scoring {

    public record Weighted(double weight, Severity severity, FindingSource source) {}

    private Scoring() {}

    public static BigDecimal score(List<Weighted> findings) {
        double sum = findings.stream().mapToDouble(f -> f.weight() * f.severity().factor()).sum();
        return BigDecimal.valueOf(Math.min(1.0, sum)).setScale(3, RoundingMode.HALF_UP);
    }

    public static CaseStatus route(BigDecimal score, PackConfig.Routing routing, List<Weighted> findings) {
        double s = score.doubleValue();
        CaseStatus status;
        if (s >= routing.escalateAtOrAbove()) {
            status = CaseStatus.ESCALATED;
        } else if (s < routing.autoClearBelow()) {
            status = CaseStatus.AUTO_CLEARED;
        } else {
            status = CaseStatus.NEEDS_REVIEW;
        }
        boolean security = findings.stream().anyMatch(f -> f.source() == FindingSource.SECURITY);
        if (security && status == CaseStatus.AUTO_CLEARED) {
            return CaseStatus.NEEDS_REVIEW;
        }
        return status;
    }
}
