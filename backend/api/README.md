# api

FastAPI + SQLite system of record: renewal calls (with the playbook guard rails), support call records, cases and a hash-chained audit log. It replaces the Spring service; the behaviour follows the deleted Java code (`git show 061e0dd^:backend/api/src`).

## Run locally

```bash
pip install -r requirements.txt
ENFORCE_CALLING_HOURS=false uvicorn app.main:app --port 8080
```

- API: http://localhost:8080/api/v1, Swagger UI: http://localhost:8080/swagger-ui.html
- Users (HTTP Basic): `analyst/analyst`, `reviewer/reviewer`, `admin/admin`, `voice/voice`

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `API_DB_PATH` | `data/runtime/api.db` (under `backend/api`) | SQLite file; the schema is created on start and the renewal seed is upserted |
| `ENFORCE_CALLING_HOURS` | `true` | Refuse new renewal calls outside 09:00–21:00 IST |
| `PII_VAULT_PATH` | `data/pii_vault.db` (under `backend/api`) | Separate SQLite file holding the values behind `[KIND#n]` transcript tokens, each Fernet-encrypted |
| `PII_VAULT_KEY` | unset | Fernet key for the vault (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`). Unset: transcripts are still redacted, but no values are kept |
| `RENEWAL_PLAYBOOK` | `app/resources/playbooks/health-renewal.yml` | Discount, payment-plan, add-on and hand-off limits |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated browser origins |

## Roles

| Who | May |
|---|---|
| `voice` (VOICE only) | write support call records; run renewal call tools (verify, policy, options, quote, payment link, hand-off, turns); read calls; end renewal calls |
| analyst, reviewer, admin (ANALYST) | renewal queue, dashboard, start/read/end renewal calls, read support calls, cases, packs, stats |
| reviewer | decide cases (not ones they started) |
| admin | `/audit/verify`, `/renewals/calls/mark-simulated` |

Java let ANALYST call the renewal tools too; here only `voice` does, since no staff client calls them.

## Tests

```bash
python -m pytest -q
```
