package ai.caseintel.api.rules;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.UUID;

public record Evidence(@JsonProperty("document_id") UUID documentId, int page, String quote) {}
