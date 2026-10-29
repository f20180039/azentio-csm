package ai.caseintel.api.jobs;

import java.util.List;
import java.util.UUID;
import java.util.concurrent.ThreadLocalRandom;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/** Postgres-backed queue: workers claim with FOR UPDATE SKIP LOCKED, so no two workers take the same job. */
@Component
public class JobQueue {

    public static final String PROCESS_CASE = "PROCESS_CASE";

    public record ClaimedJob(UUID id, UUID caseId, String kind, int attempts) {}

    private final JdbcTemplate jdbc;

    public JobQueue(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void enqueue(UUID caseId, String kind, String idempotencyKey) {
        jdbc.update("""
                insert into jobs(id, case_id, kind, status, attempts, run_after, idempotency_key, created_at, updated_at)
                values (?, ?, ?, 'PENDING', 0, now(), ?, now(), now())
                on conflict (idempotency_key) do nothing
                """, UUID.randomUUID(), caseId, kind, idempotencyKey);
    }

    public ClaimedJob claim() {
        List<ClaimedJob> rows = jdbc.query("""
                update jobs set status = 'RUNNING', attempts = attempts + 1, updated_at = now()
                where id = (
                    select id from jobs
                    where status in ('PENDING', 'RETRY') and run_after <= now()
                    order by run_after
                    for update skip locked
                    limit 1)
                returning id, case_id, kind, attempts
                """, (rs, i) -> new ClaimedJob(
                rs.getObject("id", UUID.class), rs.getObject("case_id", UUID.class),
                rs.getString("kind"), rs.getInt("attempts")));
        return rows.isEmpty() ? null : rows.get(0);
    }

    public void complete(UUID jobId) {
        jdbc.update("update jobs set status = 'DONE', last_error = null, updated_at = now() where id = ?", jobId);
    }

    public void retry(UUID jobId, int attempts, long backoffBaseMs, String error) {
        jdbc.update("""
                update jobs set status = 'RETRY', last_error = ?, updated_at = now(),
                       run_after = now() + (? * interval '1 millisecond')
                where id = ?
                """, truncate(error), backoffMs(attempts, backoffBaseMs), jobId);
    }

    public void fail(UUID jobId, String error) {
        jdbc.update("update jobs set status = 'FAILED', last_error = ?, updated_at = now() where id = ?",
                truncate(error), jobId);
    }

    public int recoverStuck(long stuckAfterSeconds) {
        return jdbc.update("""
                update jobs set status = 'RETRY', run_after = now(), updated_at = now(),
                       last_error = 'Recovered after the worker stopped responding'
                where status = 'RUNNING' and updated_at < now() - (? * interval '1 second')
                """, stuckAfterSeconds);
    }

    public long pendingCount() {
        Long n = jdbc.queryForObject("select count(*) from jobs where status in ('PENDING', 'RETRY', 'RUNNING')",
                Long.class);
        return n == null ? 0 : n;
    }

    /** Exponential backoff with up to 50% jitter: base, 2×base, 4×base… */
    static long backoffMs(int attempts, long base) {
        long exp = base * (1L << Math.max(0, Math.min(attempts - 1, 10)));
        return exp + ThreadLocalRandom.current().nextLong(base / 2 + 1);
    }

    private static String truncate(String s) {
        if (s == null) {
            return null;
        }
        return s.length() > 2000 ? s.substring(0, 2000) : s;
    }
}
