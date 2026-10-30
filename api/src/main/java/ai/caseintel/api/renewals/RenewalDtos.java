package ai.caseintel.api.renewals;

import ai.caseintel.api.domain.Severity;
import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

public final class RenewalDtos {

    private RenewalDtos() {}

    public enum Route { AGENT_CALL, HUMAN_ONLY, REMINDER_SMS }

    public record Signal(String code, String label, Severity severity, double weight) {}

    public record Risk(BigDecimal score, List<Signal> signals, Route route) {}

    public record QueueItem(String policyId, String holderName, String product, LocalDate expiresOn,
                            int daysToExpiry, BigDecimal score, List<Signal> signals, Route route) {}

    public record StartCallRequest(String policyId, Boolean simulated) {}

    public record MarkSimulatedRequest(List<UUID> callIds) {}

    public record MarkedSimulated(int marked) {}

    public record StartedCall(UUID callId, UUID caseId, String greeting) {}

    public record VerifyRequest(String dateOfBirth) {}

    public record Verification(boolean verified, int attemptsLeft, boolean mustHandoff) {}

    public record PolicyView(String policyId, String product, long sumInsured, LocalDate expiresOn, long lastPremium,
                             long renewalPremium, JsonNode breakdown, JsonNode addons, String mobileLast4,
                             boolean mustHandoff) {}

    public record RemovableAddon(String code, String name, long saving) {}

    public record Options(List<String> paymentPlans, List<RemovableAddon> removableAddons, int maxDiscountPercent,
                          boolean mustHandoff) {}

    public record QuoteRequest(List<String> dropAddons, String paymentPlan, Integer discountPercent) {}

    public record Quote(UUID quoteId, long annualPremium, int instalments, long perInstalment, boolean mustHandoff) {}

    public record PaymentLinkRequest(UUID quoteId) {}

    public record PaymentLinkSent(boolean sent, String channel, String mobileLast4, boolean mustHandoff) {}

    public record HandoffRequest(String reason, String callbackAt) {}

    public record HandoffQueued(boolean queued, boolean mustHandoff) {}

    public record TurnRequest(String role, String text, String at) {}

    public record CallEnded(String outcome, boolean mustHandoff) {}

    public record SummaryItem(String statement, String quote) {}

    public record CallView(UUID callId, UUID caseId, String policyId, String holderName, String greeting,
                           boolean identityVerified, int verifyFailures, int outOfPlaybookRequests,
                           boolean mustHandoff, String outcome, JsonNode lastQuote, boolean paymentLinkSent,
                           String handoffReason, String callbackAt, JsonNode transcript,
                           List<SummaryItem> summary) {}

    public record Kpis(long callsToday, long callsTotal, long inProgress, long renewed, long handedOff,
                       long noDecision, long premiumRetained, long premiumAtRisk, long blockedRequests,
                       long refusals, long identityFailures, double saveRate) {}

    public record DayOutcomes(LocalDate day, long renewed, long handedOff, long noDecision) {}

    public record RecentCall(UUID callId, String holderName, String policyId, String product, Instant startedAt,
                             Instant endedAt, String outcome, boolean mustHandoff, int outOfPlaybookRequests) {}

    public record GuardrailEvent(Instant at, UUID callId, String holderName, String action, String detail) {}

    public record RiskBand(String band, long count, long agentCall, long humanOnly, long reminderSms) {}

    public record Dashboard(Kpis kpis, List<DayOutcomes> outcomesByDay, List<RecentCall> recentCalls,
                            List<GuardrailEvent> guardrailEvents, List<RiskBand> riskBands) {}
}
