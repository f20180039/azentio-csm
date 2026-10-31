# web: reviewer app

React 18 + TypeScript + Vite. The reviewer-facing half of the Case Intelligence starter (see `../ARCHITECTURE.md`).

## Run

```bash
npm install
npm run dev          # against the API at VITE_API_BASE (default http://localhost:8080/api/v1)
npm run dev:mock     # no backend: in-memory example data (VITE_MOCK=1)
npm test             # Vitest
npm run build        # type-check + production bundle in dist/
```

Demo accounts (password = username): `analyst`, `reviewer`, `admin`.

Docker: `docker build -t ci-web --build-arg VITE_API_BASE=http://localhost:8080/api/v1 . && docker run -p 5173:80 ci-web`

## Screens

| Screen | What it shows |
|---|---|
| Sign in | HTTP Basic, credentials kept in memory only; role shown in the top bar |
| Queue (`/`) | Status, case type, title, risk score, ₹ at risk, findings, age. Filters by status and type (kept in the URL). Polls every 3 s while any case is processing. Header stats from `/stats` |
| New case dialog | Case type from `/packs`, multi-file upload, 20 MB client check, toast for cache HIT vs MISS |
| Case workspace (`/cases/:id`) | Findings sorted by severity then ₹, each with rule id, weight, LLM note with a verified/unverified badge, evidence links. Source text on the right with every evidence quote highlighted; clicking evidence scrolls to it. Accept / dismiss (reason required) / edit amount (reason required). Approve / reject / escalate with reason. Security banner for hidden text or prompt injection |
| Audit trail tab | Timeline with hashes; admin can verify the chain |
| Rule packs (`/packs`) | Rules, weights, rationale and parameters per pack, plus routing thresholds |

Role checks in the UI only hide controls. The API enforces RBAC; any 403 `problem+json` is shown as a toast with its `title` and `detail`.

## API shapes this client expects

`ARCHITECTURE.md` fixes the endpoints but not every JSON field. The client assumes camelCase Spring-style JSON and tolerates a few variants (see `normalise*` in `src/api/client.ts`):

- `GET /cases` → an array **or** a Spring `Page` (`content`, `totalElements`). Items: `id, caseType, title, status, riskScore, amountAtRisk, findingsCount, createdBy, createdAt`.
- `GET /cases/{id}` → the summary plus `documents[] {id, filename, sha256, pageCount}`, `findings[] {id, ruleId, title, detail, severity, weight, amount, source, evidence[{documentId, page, quote}], llmNote, verified, status, decidedBy, decisionReason, decidedAt}`, and `extraction` (or `extractions[]`) carrying the agent's `security` block as-is (`hidden_text`, `injection`, `pii`).
- `GET /cases/{id}/documents/{docId}/pages` → `[{page, text}]` or `{pages: [...]}`.
- `POST /cases` → the case summary; cache status from the `X-Cache` header (`HIT`/`MISS`), falling back to `200` = hit.
- `GET /packs` → list of `{caseType, label, extractionSchema, routing, rules}`; `rules` may be a list of `{id, weight, rationale, params}` or the YAML-style map keyed by rule id.
- `GET /stats` → `{byStatus, jobsPending, p50Ms, p95Ms, cacheHits}`.
- `GET /audit/verify` → `{valid, checked, brokenAt, detail}`.
- Optional `GET /me` → `{username, roles[]}`. Without it, sign-in probes `/packs` (any role) and `/audit/verify` (admin) to work out the role.

## Mock mode

`src/api/mock.ts` implements the same interface with example fixtures (an escalated bank statement with a balance-chain break, window dressing and hidden white text; a demo invoice; an auto-cleared salary slip). It enforces roles and the four-eyes rule, so 403 handling can be demoed. Uploads go to `PROCESSING` and settle after 4 s. All fixture names and amounts are invented.
