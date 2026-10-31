# case-intel-api

Spring Boot service for the Case Intelligence Starter: uploads, a Postgres job queue, rule packs, scoring and routing, review decisions and a hash-chained audit trail. The contract is [../ARCHITECTURE.md](../ARCHITECTURE.md); differences are in [DEVIATIONS.md](DEVIATIONS.md).

## Run locally

Needs JDK 17+ and PostgreSQL. The agent service (`../agent`) should run on port 8000.

```bash
createdb caseintel                        # or use docker compose from the repo root
DB_URL=jdbc:postgresql://localhost:5432/caseintel DB_USER=$USER DB_PASSWORD= ./mvnw spring-boot:run
```

- API: http://localhost:8080/api/v1
- Swagger UI: http://localhost:8080/swagger-ui.html
- Demo users: `analyst/analyst`, `reviewer/reviewer`, `admin/admin` (HTTP Basic)

```bash
curl -u analyst:analyst -F caseType=demo -F files=@sample.pdf -i http://localhost:8080/api/v1/cases
curl -u analyst:analyst http://localhost:8080/api/v1/cases
curl -u admin:admin http://localhost:8080/api/v1/audit/verify
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `DB_URL`, `DB_USER`, `DB_PASSWORD` | `jdbc:postgresql://localhost:5432/caseintel`, `caseintel`, `caseintel` | Database |
| `AGENT_URL` | `http://localhost:8000` | Agent service |
| `STORAGE_DIR` | `./data/uploads` | Content-addressed file store |
| `PIPELINE_VERSION` | `v1` | Part of the dedupe key; bump it to force reprocessing of identical uploads |
| `WORKER_ENABLED`, `WORKER_CONCURRENCY` | `true`, `4` | Background job worker |
| `UPLOADS_PER_MINUTE` | `30` | Per-user upload rate limit |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed browser origins |

## Adding a rule pack (topic day)

1. Add `src/main/resources/packs/<caseType>.yml` with routing thresholds and a weight plus rationale for every rule, including the core rules you want.
2. Add a `@Component` implementing `RulePack` that names the agent extraction schema and returns the pack's `Rule`s.
3. Rules read `RuleContext` (documents, extraction JSON, pack params) and return `FindingDraft`s. Money comes from code, never from the LLM.

## Tests

```bash
./mvnw test                                   # unit tests
./mvnw test -Dintegration                     # adds the Postgres tests (Testcontainers, needs Docker)
IT_DB_URL=jdbc:postgresql://localhost:5432/empty_db IT_DB_USER=$USER ./mvnw test -Dintegration -Dtest=PersistenceIT
```

## Docker

```bash
docker build -t case-intel-api .
docker run -p 8080:8080 -e DB_URL=jdbc:postgresql://host.docker.internal:5432/caseintel case-intel-api
```
