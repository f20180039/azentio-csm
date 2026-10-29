package ai.caseintel.api.renewals;

import java.util.List;

public record Playbook(
        String id,
        int version,
        String greeting,
        int maxDiscountPercent,
        List<String> paymentPlans,
        boolean removableOptionalAddons,
        int maxOutOfPlaybookRequests,
        int maxVerifyFailures) {}
