package ai.caseintel.api.rules;

import java.util.List;

public interface Rule {

    String id();

    List<FindingDraft> evaluate(RuleContext ctx);
}
