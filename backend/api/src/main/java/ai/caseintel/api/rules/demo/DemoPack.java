package ai.caseintel.api.rules.demo;

import ai.caseintel.api.rules.Rule;
import ai.caseintel.api.rules.RulePack;
import java.util.List;
import org.springframework.stereotype.Component;

@Component
public class DemoPack implements RulePack {

    @Override
    public String caseType() {
        return "demo";
    }

    @Override
    public String extractionSchema() {
        return "demo";
    }

    @Override
    public List<Rule> rules() {
        return List.of(new LargeAmountRule());
    }
}
