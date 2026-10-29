package ai.caseintel.api.rules;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Map;

/** One pack's YAML. Jackson reads {@code rules} into a LinkedHashMap, so file order is kept. */
public record PackConfig(String caseType, String label, Routing routing, Map<String, RuleConfig> rules) {

    public record Routing(double autoClearBelow, double escalateAtOrAbove) {}

    public record RuleConfig(double weight, String rationale, JsonNode params) {}
}
