package ai.caseintel.api.rules;

import ai.caseintel.api.domain.FindingSource;
import ai.caseintel.api.domain.Severity;
import java.math.BigDecimal;
import java.util.List;

public record FindingDraft(
        String ruleId,
        String title,
        String detail,
        Severity severity,
        BigDecimal amount,
        FindingSource source,
        List<Evidence> evidence) {}
