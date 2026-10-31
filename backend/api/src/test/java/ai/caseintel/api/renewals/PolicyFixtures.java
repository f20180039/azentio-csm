package ai.caseintel.api.renewals;

import java.lang.reflect.Field;
import java.math.BigDecimal;
import java.time.LocalDate;

/** PolicyEntity is read-only by design, so tests set its fields reflectively. */
public final class PolicyFixtures {

    private PolicyFixtures() {}

    public static PolicyEntity policy(String id, String name, String expiresOn, int last, int renewal) {
        PolicyEntity p = newEntity();
        set(p, "id", id);
        set(p, "holderName", name);
        set(p, "product", "Health Floater");
        set(p, "expiresOn", LocalDate.parse(expiresOn));
        set(p, "lastPremium", BigDecimal.valueOf(last));
        set(p, "renewalPremium", BigDecimal.valueOf(renewal));
        return p;
    }

    public static PolicyEntity with(PolicyEntity p, String field, Object value) {
        set(p, field, value);
        return p;
    }

    public static PolicyEntity meera() {
        return with(policy("HF-2291-0457", "Meera Iyer", "2026-11-03", 15120, 18450), "remindersIgnored", 2);
    }

    public static PolicyEntity rohan() {
        return policy("HF-1180-0233", "Rohan Das", "2026-11-19", 20000, 21800);
    }

    private static PolicyEntity newEntity() {
        try {
            var c = PolicyEntity.class.getDeclaredConstructor();
            c.setAccessible(true);
            return c.newInstance();
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException(e);
        }
    }

    private static void set(PolicyEntity p, String field, Object value) {
        try {
            Field f = PolicyEntity.class.getDeclaredField(field);
            f.setAccessible(true);
            f.set(p, value);
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException(e);
        }
    }
}
