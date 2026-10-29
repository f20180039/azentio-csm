package ai.caseintel.api.audit;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;

/**
 * hash = sha256(prev_hash || actor || action || canonical(payload) || created_at).
 * Payload keys are sorted and numbers normalised before hashing, because Postgres jsonb keeps neither key order
 * nor number spelling.
 */
public final class AuditHasher {

    public static final String GENESIS = "0".repeat(64);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private AuditHasher() {}

    public static String hash(String prevHash, String actor, String action, JsonNode payload, Instant createdAt) {
        String material = prevHash + "|" + actor + "|" + action + "|" + canonical(payload) + "|" + createdAt;
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(material.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    public static String canonical(JsonNode node) {
        try {
            return MAPPER.writeValueAsString(sorted(node));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static JsonNode sorted(JsonNode node) {
        if (node == null || node.isNull() || node.isMissingNode()) {
            return MAPPER.nullNode();
        }
        if (node.isObject()) {
            ObjectNode out = MAPPER.createObjectNode();
            List<String> names = new ArrayList<>();
            node.fieldNames().forEachRemaining(names::add);
            names.sort(String::compareTo);
            names.forEach(n -> out.set(n, sorted(node.get(n))));
            return out;
        }
        if (node.isArray()) {
            ArrayNode out = MAPPER.createArrayNode();
            node.forEach(n -> out.add(sorted(n)));
            return out;
        }
        if (node.isNumber()) {
            // jsonb rewrites number spellings (1.0E10 → 10000000000), so hash the numeric value, not the text.
            return MAPPER.getNodeFactory().textNode("n:" + node.decimalValue().stripTrailingZeros().toPlainString());
        }
        return node;
    }
}
