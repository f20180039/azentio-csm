package ai.caseintel.api.renewals;

import ai.caseintel.api.rules.InvalidPackException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import java.io.IOException;
import java.io.InputStream;
import org.springframework.core.io.ClassPathResource;

public final class PlaybookLoader {

    private static final ObjectMapper YAML = new ObjectMapper(new YAMLFactory())
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, true);

    private PlaybookLoader() {}

    public static Playbook load(String classpathPath) {
        Raw raw;
        try (InputStream in = new ClassPathResource(classpathPath).getInputStream()) {
            raw = YAML.readValue(in, Raw.class);
        } catch (IOException e) {
            throw new InvalidPackException(classpathPath + ": cannot read playbook (" + e.getMessage() + ")");
        }
        String src = classpathPath;
        if (raw == null || raw.id == null || raw.id.isBlank()) throw missing(src, "id");
        if (raw.greeting == null || raw.greeting.isBlank()) throw missing(src, "greeting");
        if (raw.paymentPlans == null || raw.paymentPlans.isEmpty()) throw missing(src, "paymentPlans");
        int version = nonNegative(src, "version", raw.version);
        int discount = nonNegative(src, "maxDiscountPercent", raw.maxDiscountPercent);
        int outOf = nonNegative(src, "maxOutOfPlaybookRequests", raw.maxOutOfPlaybookRequests);
        int verify = nonNegative(src, "maxVerifyFailures", raw.maxVerifyFailures);
        if (discount > 100) {
            throw new InvalidPackException(src + ": maxDiscountPercent must be at most 100");
        }
        if (raw.removableOptionalAddons == null) throw missing(src, "removableOptionalAddons");
        return new Playbook(raw.id, version, raw.greeting, discount, java.util.List.copyOf(raw.paymentPlans),
                raw.removableOptionalAddons, outOf, verify);
    }

    private static InvalidPackException missing(String src, String field) {
        return new InvalidPackException(src + ": " + field + " is required");
    }

    private static int nonNegative(String src, String field, Integer value) {
        if (value == null) throw missing(src, field);
        if (value < 0) throw new InvalidPackException(src + ": " + field + " must not be negative");
        return value;
    }

    private static final class Raw {
        public String id;
        public Integer version;
        public String greeting;
        public Integer maxDiscountPercent;
        public java.util.List<String> paymentPlans;
        public Boolean removableOptionalAddons;
        public Integer maxOutOfPlaybookRequests;
        public Integer maxVerifyFailures;
    }
}
