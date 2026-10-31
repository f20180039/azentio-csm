package ai.caseintel.api.renewals;

import static ai.caseintel.api.renewals.PolicyFixtures.meera;
import static ai.caseintel.api.renewals.PolicyFixtures.policy;
import static ai.caseintel.api.renewals.PolicyFixtures.rohan;
import static ai.caseintel.api.renewals.PolicyFixtures.with;
import static org.assertj.core.api.Assertions.assertThat;

import ai.caseintel.api.renewals.RenewalDtos.Risk;
import ai.caseintel.api.renewals.RenewalDtos.Route;
import ai.caseintel.api.renewals.RenewalDtos.Signal;
import java.math.BigDecimal;
import java.time.LocalDate;
import org.junit.jupiter.api.Test;

class LapseRiskTest {

    private static final LocalDate TODAY = LocalDate.parse("2026-10-29");

    @Test
    void meeraScoresAndRoutesToAgent() {
        Risk r = LapseRisk.assess(meera(), TODAY);
        assertThat(r.signals()).extracting(Signal::code)
                .containsExactly("EXPIRY_7D", "PREMIUM_UP_15", "REMINDERS_IGNORED");
        assertThat(r.score()).isEqualByComparingTo("0.850");
        assertThat(r.route()).isEqualTo(Route.AGENT_CALL);
    }

    @Test
    void openComplaintIsHumanOnly() {
        Risk r = LapseRisk.assess(with(meera(), "openComplaint", true), TODAY);
        assertThat(r.route()).isEqualTo(Route.HUMAN_ONLY);
        assertThat(LapseRisk.assess(with(meera(), "doNotCall", true), TODAY).route()).isEqualTo(Route.HUMAN_ONLY);
    }

    @Test
    void lowScoreGetsReminderSms() {
        Risk r = LapseRisk.assess(rohan(), TODAY);
        assertThat(r.signals()).extracting(Signal::code).containsExactly("PREMIUM_UP_5");
        assertThat(r.score()).isEqualByComparingTo("0.150");
        assertThat(r.route()).isEqualTo(Route.REMINDER_SMS);
    }

    @Test
    void scoreCapsAtOne() {
        var p = with(with(with(meera(), "claimRejected12m", true), "autodebitFailed", true), "remindersIgnored", 5);
        Risk r = LapseRisk.assess(p, TODAY);
        assertThat(r.score()).isEqualByComparingTo(new BigDecimal("1.000"));
        assertThat(r.signals()).hasSize(5);
    }

    @Test
    void expiryBandsAreInclusive() {
        assertThat(LapseRisk.assess(policy("a", "A", "2026-11-05", 100, 100), TODAY).signals())
                .extracting(Signal::code).containsExactly("EXPIRY_7D");
        assertThat(LapseRisk.assess(policy("a", "A", "2026-11-06", 100, 100), TODAY).signals())
                .extracting(Signal::code).containsExactly("EXPIRY_14D");
        assertThat(LapseRisk.assess(policy("a", "A", "2026-11-12", 100, 100), TODAY).signals())
                .extracting(Signal::code).containsExactly("EXPIRY_14D");
        assertThat(LapseRisk.assess(policy("a", "A", "2026-11-13", 100, 100), TODAY).signals()).isEmpty();
    }
}
