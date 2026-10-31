package ai.caseintel.api.config;

import ai.caseintel.api.renewals.Playbook;
import ai.caseintel.api.renewals.PlaybookLoader;
import java.time.Clock;
import java.time.ZoneId;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class RenewalConfig {

    @Bean
    Clock clock() {
        return Clock.system(ZoneId.of("Asia/Kolkata"));
    }

    @Bean
    Playbook playbook(AppProperties props) {
        return PlaybookLoader.load(props.renewals().playbook());
    }
}
