package ai.caseintel.api.rules;

import com.fasterxml.jackson.databind.JsonNode;

public final class Extractions {

    private Extractions() {}

    /** First page whose text contains {@code quote}, ignoring case and whitespace runs; page 1 when not found. */
    public static int pageOf(JsonNode extraction, String quote) {
        if (extraction == null || quote == null || quote.isBlank()) {
            return 1;
        }
        String needle = normalise(quote);
        for (JsonNode p : extraction.path("pages")) {
            if (normalise(p.path("text").asText()).contains(needle)) {
                return p.path("page").asInt(1);
            }
        }
        return 1;
    }

    static String normalise(String s) {
        return s.replaceAll("\\s+", " ").trim().toLowerCase();
    }
}
