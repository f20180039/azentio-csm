package ai.caseintel.api.service;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.stereotype.Component;

/** In-memory counters for /stats. Resets on restart; the window keeps the last 1,000 processed cases. */
@Component
public class ProcessingMetrics {

    private static final int WINDOW = 1000;

    private final Deque<Long> durationsMs = new ArrayDeque<>();
    private final AtomicLong cacheHits = new AtomicLong();
    private final AtomicLong cacheMisses = new AtomicLong();

    public synchronized void recordProcessing(long ms) {
        if (durationsMs.size() == WINDOW) {
            durationsMs.removeFirst();
        }
        durationsMs.addLast(ms);
    }

    public void cacheHit() {
        cacheHits.incrementAndGet();
    }

    public void cacheMiss() {
        cacheMisses.incrementAndGet();
    }

    public long cacheHits() {
        return cacheHits.get();
    }

    public long cacheMisses() {
        return cacheMisses.get();
    }

    public synchronized Long percentile(double p) {
        if (durationsMs.isEmpty()) {
            return null;
        }
        List<Long> sorted = new ArrayList<>(durationsMs);
        Collections.sort(sorted);
        int idx = (int) Math.ceil(p * sorted.size()) - 1;
        return sorted.get(Math.max(0, Math.min(idx, sorted.size() - 1)));
    }

    public synchronized int samples() {
        return durationsMs.size();
    }
}
