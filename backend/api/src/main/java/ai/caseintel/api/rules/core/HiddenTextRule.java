package ai.caseintel.api.rules.core;

import ai.caseintel.api.domain.DocumentEntity;
import ai.caseintel.api.domain.FindingSource;
import ai.caseintel.api.domain.Severity;
import ai.caseintel.api.rules.CoreRule;
import ai.caseintel.api.rules.Evidence;
import ai.caseintel.api.rules.FindingDraft;
import ai.caseintel.api.rules.RuleContext;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Component;

@Component
public class HiddenTextRule implements CoreRule {

    public static final String ID = "CORE-HIDDEN-TEXT";

    @Override
    public String id() {
        return ID;
    }

    @Override
    public List<FindingDraft> evaluate(RuleContext ctx) {
        List<FindingDraft> out = new ArrayList<>();
        for (DocumentEntity doc : ctx.documents()) {
            JsonNode extraction = ctx.extractions().get(doc.getId());
            if (extraction == null) {
                continue;
            }
            JsonNode hidden = extraction.path("security").path("hidden_text");
            if (!hidden.isArray() || hidden.isEmpty()) {
                continue;
            }
            List<Evidence> evidence = new ArrayList<>();
            List<String> reasons = new ArrayList<>();
            for (JsonNode h : hidden) {
                evidence.add(new Evidence(doc.getId(), h.path("page").asInt(1), h.path("text").asText()));
                reasons.add(h.path("reason").asText("hidden"));
            }
            out.add(new FindingDraft(ID,
                    "Hidden text in " + doc.getFilename(),
                    hidden.size() + " text span(s) a reader cannot see (" + String.join(", ", reasons.stream().distinct().toList())
                            + "). They were excluded from everything sent to the AI model.",
                    Severity.HIGH, null, FindingSource.SECURITY, evidence));
        }
        return out;
    }
}
