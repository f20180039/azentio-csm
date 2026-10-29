package ai.caseintel.api.rules.demo;

import ai.caseintel.api.domain.DocumentEntity;
import ai.caseintel.api.domain.FindingSource;
import ai.caseintel.api.domain.Severity;
import ai.caseintel.api.rules.Evidence;
import ai.caseintel.api.rules.Extractions;
import ai.caseintel.api.rules.FindingDraft;
import ai.caseintel.api.rules.Rule;
import ai.caseintel.api.rules.RuleContext;
import com.fasterxml.jackson.databind.JsonNode;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

public class LargeAmountRule implements Rule {

    public static final String ID = "DEMO-LARGE-AMOUNT";

    @Override
    public String id() {
        return ID;
    }

    @Override
    public List<FindingDraft> evaluate(RuleContext ctx) {
        JsonNode params = ctx.params(ID);
        BigDecimal threshold = params == null ? new BigDecimal("100000") : params.path("threshold").decimalValue();
        List<FindingDraft> out = new ArrayList<>();
        for (DocumentEntity doc : ctx.documents()) {
            JsonNode extraction = ctx.extractions().get(doc.getId());
            if (extraction == null) {
                continue;
            }
            for (JsonNode a : extraction.path("fields").path("amounts")) {
                if (!a.path("value").isNumber()) {
                    continue;
                }
                BigDecimal value = a.path("value").decimalValue();
                if (value.compareTo(threshold) <= 0) {
                    continue;
                }
                String context = a.path("context").asText("");
                out.add(new FindingDraft(ID,
                        "Amount above " + threshold.toPlainString(),
                        a.path("currency").asText("INR") + " " + value.toPlainString() + " in " + doc.getFilename(),
                        Severity.MEDIUM, value, FindingSource.RULE,
                        context.isBlank() ? List.of()
                                : List.of(new Evidence(doc.getId(), Extractions.pageOf(extraction, context), context))));
            }
        }
        return out;
    }
}
