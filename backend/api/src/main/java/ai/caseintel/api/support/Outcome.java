package ai.caseintel.api.support;

public enum Outcome {
    RESOLVED, TICKET_CREATED, COMPLAINT_REGISTERED, ROUTED, ESCALATED, ABANDONED;

    public static Outcome parse(String value) {
        return Vocabulary.parse(Outcome.class, "outcome", value);
    }
}
