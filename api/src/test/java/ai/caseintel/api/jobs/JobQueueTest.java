package ai.caseintel.api.jobs;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class JobQueueTest {

    @Test
    void backoffDoublesPerAttemptWithBoundedJitter() {
        for (int i = 0; i < 50; i++) {
            assertThat(JobQueue.backoffMs(1, 2000)).isBetween(2000L, 3000L);
            assertThat(JobQueue.backoffMs(2, 2000)).isBetween(4000L, 5000L);
            assertThat(JobQueue.backoffMs(3, 2000)).isBetween(8000L, 9000L);
        }
    }
}
