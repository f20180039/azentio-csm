package ai.caseintel.api.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.Test;

class UploadRateLimiterTest {

    @Test
    void allowsBurstUpToCapacityThenRefills() {
        AtomicLong now = new AtomicLong();
        UploadRateLimiter limiter = new UploadRateLimiter(3, now::get);

        limiter.acquire("a");
        limiter.acquire("a");
        limiter.acquire("a");
        assertThatThrownBy(() -> limiter.acquire("a"))
                .isInstanceOfSatisfying(RateLimitedException.class,
                        e -> assertThat(e.retryAfterSeconds()).isEqualTo(20));

        limiter.acquire("b");

        now.addAndGet(20_000_000_000L);
        limiter.acquire("a");
    }
}
