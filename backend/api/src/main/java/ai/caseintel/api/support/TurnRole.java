package ai.caseintel.api.support;

import ai.caseintel.api.service.ApiException;

/** Wire values are lowercase, as in the shared contract. */
public enum TurnRole {
    CUSTOMER("customer"), AGENT("agent");

    private final String wire;

    TurnRole(String wire) {
        this.wire = wire;
    }

    public String wire() {
        return wire;
    }

    public static TurnRole parse(String value) {
        for (TurnRole r : values()) {
            if (r.wire.equals(value)) {
                return r;
            }
        }
        throw ApiException.badRequest("role must be one of customer, agent"
                + (value == null ? "" : "; got '" + value + "'"));
    }
}
