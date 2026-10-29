package ai.caseintel.api.rules;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.List;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;

public final class PackConfigLoader {

    private static final ObjectMapper YAML = new ObjectMapper(new YAMLFactory())
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, true);

    private PackConfigLoader() {}

    public static List<PackConfig> loadAll(String locationPattern) {
        try {
            Resource[] resources = new PathMatchingResourcePatternResolver().getResources(locationPattern);
            List<PackConfig> packs = new ArrayList<>();
            for (Resource r : resources) {
                try (InputStream in = r.getInputStream()) {
                    packs.add(parse(in, r.getFilename()));
                }
            }
            return packs;
        } catch (IOException e) {
            throw new UncheckedIOException("Cannot read packs at " + locationPattern, e);
        }
    }

    public static PackConfig parse(InputStream in, String source) throws IOException {
        PackConfig pack = YAML.readValue(in, PackConfig.class);
        validate(pack, source);
        return pack;
    }

    static void validate(PackConfig p, String source) {
        if (p.caseType() == null || p.caseType().isBlank()) {
            throw new InvalidPackException(source + ": caseType is required");
        }
        if (p.routing() == null) {
            throw new InvalidPackException(source + ": routing is required");
        }
        double low = p.routing().autoClearBelow();
        double high = p.routing().escalateAtOrAbove();
        if (low < 0 || high > 1 || low >= high) {
            throw new InvalidPackException(source + ": routing needs 0 <= autoClearBelow < escalateAtOrAbove <= 1");
        }
        if (p.rules() == null || p.rules().isEmpty()) {
            throw new InvalidPackException(source + ": at least one rule is required");
        }
        p.rules().forEach((id, rc) -> {
            if (rc.weight() < 0 || rc.weight() > 1) {
                throw new InvalidPackException(source + ": weight of " + id + " must be between 0 and 1");
            }
            if (rc.rationale() == null || rc.rationale().isBlank()) {
                throw new InvalidPackException(source + ": " + id + " needs a rationale for its weight");
            }
        });
    }
}
