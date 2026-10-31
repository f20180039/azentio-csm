package ai.caseintel.api.domain;

public enum Severity {
    LOW(0.3), MEDIUM(0.6), HIGH(1.0);

    private final double factor;

    Severity(double factor) {
        this.factor = factor;
    }

    public double factor() {
        return factor;
    }
}
