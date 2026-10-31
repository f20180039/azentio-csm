package ai.caseintel.api.rules;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.Test;

class PackConfigLoaderTest {

    @Test
    void loadsDemoPackFromClasspathInFileOrder() {
        List<PackConfig> packs = PackConfigLoader.loadAll("classpath*:packs/*.yml");
        PackConfig demo = packs.stream().filter(p -> p.caseType().equals("demo")).findFirst().orElseThrow();

        assertThat(demo.routing().autoClearBelow()).isEqualTo(0.2);
        assertThat(demo.routing().escalateAtOrAbove()).isEqualTo(0.8);
        assertThat(demo.rules().keySet())
                .containsExactly("CORE-DUPLICATE-DOC", "CORE-HIDDEN-TEXT", "CORE-INJECTION", "DEMO-LARGE-AMOUNT");
        assertThat(demo.rules().get("DEMO-LARGE-AMOUNT").params().path("threshold").asInt()).isEqualTo(100000);
        assertThat(demo.rules().get("CORE-INJECTION").rationale()).isNotBlank();
    }

    @Test
    void rejectsInvertedThresholds() {
        assertThatThrownBy(() -> parse("""
                caseType: x
                routing: { autoClearBelow: 0.9, escalateAtOrAbove: 0.5 }
                rules:
                  R1: { weight: 0.5, rationale: "r" }
                """)).isInstanceOf(InvalidPackException.class).hasMessageContaining("autoClearBelow");
    }

    @Test
    void rejectsWeightOutOfRange() {
        assertThatThrownBy(() -> parse("""
                caseType: x
                routing: { autoClearBelow: 0.2, escalateAtOrAbove: 0.8 }
                rules:
                  R1: { weight: 1.5, rationale: "r" }
                """)).isInstanceOf(InvalidPackException.class).hasMessageContaining("weight of R1");
    }

    @Test
    void rejectsWeightWithoutRationale() {
        assertThatThrownBy(() -> parse("""
                caseType: x
                routing: { autoClearBelow: 0.2, escalateAtOrAbove: 0.8 }
                rules:
                  R1: { weight: 0.5 }
                """)).isInstanceOf(InvalidPackException.class).hasMessageContaining("rationale");
    }

    @Test
    void rejectsUnknownKeys() {
        assertThatThrownBy(() -> parse("""
                caseType: x
                routng: { autoClearBelow: 0.2, escalateAtOrAbove: 0.8 }
                rules:
                  R1: { weight: 0.5, rationale: "r" }
                """)).isInstanceOf(Exception.class);
    }

    private static PackConfig parse(String yaml) throws Exception {
        return PackConfigLoader.parse(new ByteArrayInputStream(yaml.getBytes(StandardCharsets.UTF_8)), "test.yml");
    }
}
