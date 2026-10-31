package ai.caseintel.api.jobs;

import ai.caseintel.api.audit.AuditService;
import ai.caseintel.api.config.AppProperties;
import ai.caseintel.api.domain.CaseStatus;
import ai.caseintel.api.repo.CaseRepository;
import jakarta.annotation.PreDestroy;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "app.worker", name = "enabled", havingValue = "true", matchIfMissing = true)
public class JobWorker {

    private static final Logger log = LoggerFactory.getLogger(JobWorker.class);

    private final JobQueue queue;
    private final CaseProcessor processor;
    private final CaseRepository cases;
    private final AuditService audit;
    private final AppProperties.Worker cfg;
    private final ExecutorService pool;
    private final Semaphore slots;

    public JobWorker(JobQueue queue, CaseProcessor processor, CaseRepository cases, AuditService audit,
                     AppProperties props) {
        this.queue = queue;
        this.processor = processor;
        this.cases = cases;
        this.audit = audit;
        this.cfg = props.worker();
        this.pool = Executors.newFixedThreadPool(cfg.concurrency());
        this.slots = new Semaphore(cfg.concurrency());
    }

    @Scheduled(fixedDelayString = "${app.worker.poll-interval-ms:500}")
    public void poll() {
        while (slots.tryAcquire()) {
            JobQueue.ClaimedJob job;
            try {
                job = queue.claim();
            } catch (RuntimeException e) {
                slots.release();
                log.warn("Job claim failed: {}", e.getMessage());
                return;
            }
            if (job == null) {
                slots.release();
                return;
            }
            pool.submit(() -> {
                try {
                    run(job);
                } catch (Throwable t) {
                    log.error("Job {} crashed the worker thread", job.id(), t);
                } finally {
                    slots.release();
                }
            });
        }
    }

    @Scheduled(fixedDelay = 60_000, initialDelay = 5_000)
    public void recoverStuck() {
        int n = queue.recoverStuck(cfg.stuckAfter().toSeconds());
        if (n > 0) {
            log.warn("Requeued {} job(s) stuck in RUNNING", n);
        }
    }

    void run(JobQueue.ClaimedJob job) {
        boolean lastAttempt = job.attempts() >= cfg.maxAttempts();
        try {
            if (JobQueue.PROCESS_CASE.equals(job.kind())) {
                processor.process(job.caseId(), job.attempts(), lastAttempt);
            }
            queue.complete(job.id());
        } catch (RuntimeException | Error e) {
            String error = e.getClass().getSimpleName() + ": " + e.getMessage();
            if (lastAttempt) {
                log.error("Job {} failed for good after {} attempt(s)", job.id(), job.attempts(), e);
                queue.fail(job.id(), error);
                markCaseFailed(job, error);
            } else {
                log.warn("Job {} attempt {} failed, retrying: {}", job.id(), job.attempts(), error);
                queue.retry(job.id(), job.attempts(), cfg.backoffBaseMs(), error);
                audit.record(job.caseId(), "system", "JOB_RETRY",
                        Map.of("jobId", job.id().toString(), "attempt", job.attempts(), "error", error));
            }
        }
    }

    private void markCaseFailed(JobQueue.ClaimedJob job, String error) {
        cases.findById(job.caseId()).ifPresent(c -> {
            c.setStatus(CaseStatus.FAILED);
            cases.save(c);
        });
        audit.record(job.caseId(), "system", "JOB_FAILED",
                Map.of("jobId", job.id().toString(), "attempts", job.attempts(), "error", error));
    }

    @PreDestroy
    void shutdown() throws InterruptedException {
        pool.shutdown();
        pool.awaitTermination(10, TimeUnit.SECONDS);
    }
}
