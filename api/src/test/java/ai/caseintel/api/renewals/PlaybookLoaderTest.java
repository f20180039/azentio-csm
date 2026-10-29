package ai.caseintel.api.renewals;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import ai.caseintel.api.rules.InvalidPackException;
import org.junit.jupiter.api.Test;

class PlaybookLoaderTest {

    @Test
    void loadsDemoPlaybook() {
        Playbook p = PlaybookLoader.load("playbooks/health-renewal.yml");
        assertThat(p.id()).isEqualTo("health-renewal");
        assertThat(p.version()).isEqualTo(3);
        assertThat(p.greeting()).isEqualTo("Hello, this call is recorded. I'm the renewals assistant from "
                + "Lotusleaf General Insurance. Am I speaking with {holderName}?");
        assertThat(p.maxDiscountPercent()).isZero();
        assertThat(p.paymentPlans()).containsExactly("annual", "quarterly");
        assertThat(p.removableOptionalAddons()).isTrue();
        assertThat(p.maxOutOfPlaybookRequests()).isEqualTo(2);
        assertThat(p.maxVerifyFailures()).isEqualTo(3);
    }

    @Test
    void rejectsNegativeDiscount() {
        assertThatThrownBy(() -> PlaybookLoader.load("playbooks/negative-discount.yml"))
                .isInstanceOf(InvalidPackException.class).hasMessageContaining("maxDiscountPercent");
    }

    @Test
    void rejectsMissingFile() {
        assertThatThrownBy(() -> PlaybookLoader.load("playbooks/nope.yml")).isInstanceOf(InvalidPackException.class);
    }
}
