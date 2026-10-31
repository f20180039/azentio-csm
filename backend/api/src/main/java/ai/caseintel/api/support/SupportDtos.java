package ai.caseintel.api.support;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

public final class SupportDtos {

    private SupportDtos() {}

    public record StartRequest(String channel) {}

    public record Started(UUID id) {}

    public record TurnRequest(String role, String text, String at, JsonNode meta) {}

    public record TurnAdded(int seq) {}

    public record EndRequest(String outcome) {}

    public record Ended(UUID id, Outcome outcome, Instant endedAt) {}

    public record Turn(int seq, String role, String text, String at, JsonNode meta) {}

    public record CallDetail(UUID id, Channel channel, Instant startedAt, Instant endedAt, Outcome outcome,
                             boolean verified, List<Turn> turns) {}

    public record CallSummary(UUID id, Channel channel, Instant startedAt, Instant endedAt, Outcome outcome,
                              boolean verified, int turnCount, List<String> intents) {}

    public record CallList(List<CallSummary> items) {}
}
