package ai.caseintel.api.rules;

import java.util.List;

public interface RulePack {

    String caseType();

    String extractionSchema();

    List<Rule> rules();
}
