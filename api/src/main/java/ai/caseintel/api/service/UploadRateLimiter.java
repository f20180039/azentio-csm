package ai.caseintel.api.service;

import ai.caseintel.api.config.AppProperties;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.LongSupplier;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

/** Token bucket per user: capacity = uploads per minute, refilled continuously. */
@Component
public class UploadRateLimiter {

    private final double capacity;
    private final double refillPerNano;
    private final LongSupplier clock;
    private final Map<String, Bucket> buckets = new ConcurrentHashMap<>();

    @Autowired
    public UploadRateLimiter(AppProperties props) {
        this(props.rateLimit().uploadsPerMinute(), System::nanoTime);
    }

    UploadRateLimiter(int perMinute, LongSupplier clock) {
        this.capacity = perMinute;
        this.refillPerNano = perMinute / 60e9;
        this.clock = clock;
    }

    public void acquire(String user) {
        buckets.computeIfAbsent(user, u -> new Bucket(capacity, clock.getAsLong())).take();
    }

    private final class Bucket {
        private double tokens;
        private long last;

        Bucket(double tokens, long now) {
            this.tokens = tokens;
            this.last = now;
        }

        synchronized void take() {
            long now = clock.getAsLong();
            tokens = Math.min(capacity, tokens + (now - last) * refillPerNano);
            last = now;
            if (tokens < 1) {
                throw new RateLimitedException((long) Math.ceil((1 - tokens) / refillPerNano / 1e9));
            }
            tokens -= 1;
        }
    }
}
