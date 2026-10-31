package ai.caseintel.api.audit;

import java.util.List;

public final class AuditChain {

    public record Verification(boolean valid, long checked, Long brokenAt, String detail) {}

    private AuditChain() {}

    /** Rows must be in id order and start at the genesis link. */
    public static Verification verify(List<AuditRow> rows) {
        String expectedPrev = AuditHasher.GENESIS;
        long checked = 0;
        for (AuditRow row : rows) {
            if (!row.prevHash().equals(expectedPrev)) {
                return new Verification(false, checked, row.id(), "prev_hash does not match the previous event");
            }
            String recomputed = AuditHasher.hash(row.prevHash(), row.actor(), row.action(), row.payload(), row.createdAt());
            if (!recomputed.equals(row.hash())) {
                return new Verification(false, checked, row.id(), "hash does not match the event contents");
            }
            expectedPrev = row.hash();
            checked++;
        }
        return new Verification(true, checked, null, "All " + checked + " events verified");
    }
}
