package ai.caseintel.api.rules.core;

import ai.caseintel.api.domain.DocumentEntity;
import ai.caseintel.api.domain.FindingSource;
import ai.caseintel.api.domain.Severity;
import ai.caseintel.api.rules.CoreRule;
import ai.caseintel.api.rules.FindingDraft;
import ai.caseintel.api.rules.RuleContext;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Component;

@Component
public class DuplicateDocumentRule implements CoreRule {

    public static final String ID = "CORE-DUPLICATE-DOC";

    @Override
    public String id() {
        return ID;
    }

    @Override
    public List<FindingDraft> evaluate(RuleContext ctx) {
        List<FindingDraft> out = new ArrayList<>();
        for (DocumentEntity doc : ctx.documents()) {
            List<UUID> others = ctx.otherCasesWithSha().apply(doc);
            if (others.isEmpty()) {
                continue;
            }
            out.add(new FindingDraft(ID,
                    "Same file already used in " + others.size() + " other case(s)",
                    doc.getFilename() + " (SHA-256 " + doc.getSha256().substring(0, 12) + "…) also appears in: "
                            + String.join(", ", others.stream().map(UUID::toString).toList()),
                    Severity.MEDIUM, null, FindingSource.RULE, List.of()));
        }
        return out;
    }
}
