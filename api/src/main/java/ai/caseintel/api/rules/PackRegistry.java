package ai.caseintel.api.rules;

import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/** Joins pack beans (code) with pack YAML (weights, thresholds, rationale) and the core rules every pack inherits. */
@Component
public class PackRegistry {

    private static final Logger log = LoggerFactory.getLogger(PackRegistry.class);

    public record Pack(RulePack code, PackConfig config, List<Rule> rules) {}

    private final Map<String, Pack> packs;
    private final List<String> coreRuleIds;

    @Autowired
    public PackRegistry(List<RulePack> packBeans, List<CoreRule> coreRules) {
        this(packBeans, coreRules, PackConfigLoader.loadAll("classpath*:packs/*.yml"));
    }

    PackRegistry(List<RulePack> packBeans, List<CoreRule> coreRules, List<PackConfig> configs) {
        Map<String, PackConfig> byType = configs.stream()
                .collect(Collectors.toMap(PackConfig::caseType, Function.identity()));
        this.coreRuleIds = coreRules.stream().map(Rule::id).toList();
        this.packs = packBeans.stream().collect(Collectors.toMap(RulePack::caseType, bean -> {
            PackConfig cfg = byType.get(bean.caseType());
            if (cfg == null) {
                throw new InvalidPackException("No packs/" + bean.caseType() + ".yml for pack bean " + bean.caseType());
            }
            List<Rule> all = new ArrayList<>(coreRules);
            all.addAll(bean.rules());
            List<String> order = new ArrayList<>(cfg.rules().keySet());
            List<Rule> enabled = all.stream().filter(r -> {
                boolean configured = cfg.rules().containsKey(r.id());
                if (!configured) {
                    log.warn("Rule {} has no weight in packs/{}.yml and is skipped", r.id(), bean.caseType());
                }
                return configured;
            }).sorted(Comparator.comparingInt(r -> order.indexOf(r.id()))).toList();
            return new Pack(bean, cfg, enabled);
        }));
    }

    public Optional<Pack> find(String caseType) {
        return Optional.ofNullable(packs.get(caseType));
    }

    public Collection<Pack> all() {
        return packs.values();
    }

    public boolean isCore(String ruleId) {
        return coreRuleIds.contains(ruleId);
    }
}
