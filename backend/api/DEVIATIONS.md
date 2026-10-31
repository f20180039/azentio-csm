# Deviations from ARCHITECTURE.md

| Area | Contract | What the API does | Why |
|---|---|---|---|
| JSON shapes | Not fixed in the contract | camelCase everywhere. `GET /cases/{id}` returns the case fields at top level plus `documents[]` (each with `extraction`), `findings[]` and `extractions[]` (`{documentId, extraction}`). The agent's `security` block passes through unchanged in snake_case. | Agreed with the web app |
| `/stats` | "counts by status, jobs pending, p50/p95 processing ms, cache hits" | `{byStatus, jobsPending, p50Ms, p95Ms, samples, cacheHits, cacheMisses}` | Agreed with the web app. p50/p95 and the cache counters are in memory (last 1,000 cases) and reset on restart. |
| `/audit/verify` | "reports the first broken link" | `{valid, checked, brokenAt, detail}` | Agreed with the web app |
| `GET /api/v1/me` | Not in the contract | `{username, roles[]}` for any signed-in user | Needed by the web app |
| `POST /cases` (cache hit) | Return the existing case with `200` | Same, and the body is the full case detail, like a `201` | One response shape for the client |
| Explain failures | A failed agent call marks the job for retry | Extract failures always retry. An `/v1/explain` failure retries too, but on the last attempt the case is routed without LLM notes and `EXPLAIN_SKIPPED` is audited. | The rule findings are deterministic and still valid without notes |
| Security findings and `/v1/explain` | All findings explained | Findings with `source = SECURITY` (hidden text, injection) are never sent to the LLM; their `verified` stays `null` | Their evidence is the hostile text itself |
| Case decisions | `{action, reason}` | `reason` is required for every action, including `APPROVE`. Decisions need status `NEEDS_REVIEW`, `ESCALATED` or `AUTO_CLEARED` (else `409`). | Every disposition is explained in the audit trail |
| Audit hash | `sha256(prev_hash ‖ actor ‖ action ‖ payload ‖ created_at)` | Same, with `|` separators, payload keys sorted and numbers normalised before hashing, and `created_at` truncated to microseconds | Postgres `jsonb` does not keep key order or number spelling, and `timestamptz` keeps microseconds; without this a re-read would not hash the same |
| Audit append-only | Trigger on `UPDATE` and `DELETE` | Also a statement trigger on `TRUNCATE` | Closes the obvious bypass |
| Page limit | Max 50 pages per PDF | Counted at upload with PDFBox for files starting with `%PDF-`; other file types are accepted without a page count | Rejects early (`422`) instead of after queueing |
| Jobs table | Not specified | `status` check constraint: `PENDING, RUNNING, RETRY, DONE, FAILED`. Jobs stuck in `RUNNING` for 5 minutes are requeued. | Crash recovery |
| Case list | Spring `Page` | Spring `Page` serialised as-is (`content`, `totalElements`, …). Spring logs a warning that this shape is not guaranteed stable. | Matches what the web app reads today |
