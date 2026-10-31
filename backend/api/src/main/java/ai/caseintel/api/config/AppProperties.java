package ai.caseintel.api.config;

import java.time.Duration;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app")
public record AppProperties(
        String pipelineVersion,
        Storage storage,
        Limits limits,
        RateLimit rateLimit,
        Cors cors,
        Agent agent,
        Worker worker,
        Renewals renewals) {

    public record Storage(String dir) {}

    public record Limits(int maxPages) {}

    public record RateLimit(int uploadsPerMinute) {}

    public record Cors(List<String> allowedOrigins) {}

    public record Agent(String baseUrl, Duration connectTimeout, Duration readTimeout, Duration healthTimeout) {}

    public record Renewals(boolean enforceCallingHours, String playbook) {}

    public record Worker(
            boolean enabled,
            int concurrency,
            long pollIntervalMs,
            int maxAttempts,
            long backoffBaseMs,
            Duration stuckAfter) {}
}
