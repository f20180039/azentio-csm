package ai.caseintel.api.renewals;

import ai.caseintel.api.domain.Severity;
import java.math.BigDecimal;
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

    public record StartCallRequest(String policyId) {}

    public record StartedCall(UUID callId, UUID caseId, String greeting) {}
}
