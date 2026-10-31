package ai.caseintel.api.renewals;

import ai.caseintel.api.domain.FindingSource;
import ai.caseintel.api.domain.Severity;
import ai.caseintel.api.renewals.RenewalDtos.Risk;
import ai.caseintel.api.renewals.RenewalDtos.Route;
import ai.caseintel.api.renewals.RenewalDtos.Signal;
import ai.caseintel.api.rules.Scoring;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.List;

public final class LapseRisk {

    static final double REMINDER_BELOW = 0.35;

    private LapseRisk() {}

    public static Risk assess(PolicyEntity p, LocalDate today) {
        List<Signal> signals = new ArrayList<>();
        long days = ChronoUnit.DAYS.between(today, p.getExpiresOn());
        if (days >= 0 && days <= 7) {
            signals.add(new Signal("EXPIRY_7D", "Expires within 7 days", Severity.HIGH, 0.40));
        } else if (days >= 8 && days <= 14) {
            signals.add(new Signal("EXPIRY_14D", "Expires within 14 days", Severity.MEDIUM, 0.40));
        }
        // ratio = renewal / last, compared as integers to avoid rounding at the 1.05 and 1.15 edges
        BigDecimal renewal100 = p.getRenewalPremium().multiply(BigDecimal.valueOf(100));
        if (renewal100.compareTo(p.getLastPremium().multiply(BigDecimal.valueOf(115))) >= 0) {
            signals.add(new Signal("PREMIUM_UP_15", "Premium up 15% or more", Severity.MEDIUM, 0.50));
        } else if (renewal100.compareTo(p.getLastPremium().multiply(BigDecimal.valueOf(105))) >= 0) {
            signals.add(new Signal("PREMIUM_UP_5", "Premium up 5% to 15%", Severity.LOW, 0.50));
        }
        if (p.isClaimRejected12m()) {
            signals.add(new Signal("CLAIM_REJECTED", "Claim rejected in the last 12 months", Severity.HIGH, 0.30));
        }
        if (p.isAutodebitFailed()) {
            signals.add(new Signal("AUTODEBIT_FAILED", "Last auto-debit failed", Severity.MEDIUM, 0.40));
        }
        if (p.getRemindersIgnored() >= 2) {
            signals.add(new Signal("REMINDERS_IGNORED", "Ignored two or more reminders", Severity.LOW, 0.50));
        }
        BigDecimal score = Scoring.score(signals.stream()
                .map(s -> new Scoring.Weighted(s.weight(), s.severity(), FindingSource.RULE)).toList());
        Route route;
        if (p.isOpenComplaint() || p.isDoNotCall()) {
            route = Route.HUMAN_ONLY;
        } else if (score.doubleValue() < REMINDER_BELOW) {
            route = Route.REMINDER_SMS;
        } else {
            route = Route.AGENT_CALL;
        }
        return new Risk(score, List.copyOf(signals), route);
    }
}
