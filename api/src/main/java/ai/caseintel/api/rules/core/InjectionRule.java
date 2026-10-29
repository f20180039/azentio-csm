package ai.caseintel.api.rules.core;

import ai.caseintel.api.domain.DocumentEntity;
import ai.caseintel.api.domain.FindingSource;
import ai.caseintel.api.domain.Severity;
import ai.caseintel.api.rules.CoreRule;
import ai.caseintel.api.rules.Evidence;
import ai.caseintel.api.rules.Extractions;
import ai.caseintel.api.rules.FindingDraft;
import ai.caseintel.api.rules.RuleContext;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Component;

@Component
public class InjectionRule implements CoreRule {

    public static final String ID = "CORE-INJECTION";

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
            JsonNode inj = extraction.path("security").path("injection");
            if (!inj.path("suspected").asBoolean(false)) {
                continue;
            }
            List<Evidence> evidence = new ArrayList<>();
            List<String> matches = new ArrayList<>();
            for (JsonNode m : inj.path("matches")) {
                matches.add(m.asText());
                evidence.add(new Evidence(doc.getId(), Extractions.pageOf(extraction, m.asText()), m.asText()));
            }
            out.add(new FindingDraft(ID,
                    "Instructions aimed at the AI in " + doc.getFilename(),
                    "Injection score " + inj.path("score").asText("?") + ". Matched: " + String.join("; ", matches)
                            + ". The document is treated as data only, and this case cannot be auto-cleared.",
                    Severity.HIGH, null, FindingSource.SECURITY, evidence));
        }
        return out;
    }
}
