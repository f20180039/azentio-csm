package ai.caseintel.api.rules;

import ai.caseintel.api.domain.CaseEntity;
import ai.caseintel.api.domain.DocumentEntity;
import com.fasterxml.jackson.databind.JsonNode;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Function;

/**
 * Everything a rule may read. {@code otherCasesWithSha} answers "which other cases already hold this file" and
 * {@code peers} gives other cases of the same type, so rules stay free of repository dependencies and easy to unit test.
 */
public record RuleContext(
        CaseEntity caseEntity,
        List<DocumentEntity> documents,
        Map<UUID, JsonNode> extractions,
        PackConfig pack,
        Function<DocumentEntity, List<UUID>> otherCasesWithSha,
        Peers peers) {

    public RuleContext(CaseEntity caseEntity, List<DocumentEntity> documents, Map<UUID, JsonNode> extractions,
                       PackConfig pack, Function<DocumentEntity, List<UUID>> otherCasesWithSha) {
        this(caseEntity, documents, extractions, pack, otherCasesWithSha, Peers.NONE);
    }

    public JsonNode params(String ruleId) {
        PackConfig.RuleConfig rc = pack.rules().get(ruleId);
        return rc == null ? null : rc.params();
    }
}
