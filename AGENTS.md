# Instructions for coding agents (Claude Code, Codex, Cursor, …)

Team repo for the Azentio.ai Build Labs hackathon, problem #05: a customer-service voice agent for a bank. Three people work in parallel, and each has their own task file.

## 1. Find out whose agent you are

Check `git config user.email`, then `gh api user --jq .login` if the GitHub CLI is signed in:

| Person | GitHub login / email | Your task file |
|---|---|---|
| Chirag | `chiraghs` / `chiraghs1929@gmail.com` | `docs/team/tasks-chirag.md` |
| Pavan | `pavanmandavilli` | `docs/team/tasks-pavan.md` |
| Anshuman | `f20180039` / `anshuman.singh@healthplix.com` | `docs/team/tasks-anshuman.md` |

If neither matches, ask the human which person they are. **Work only on tasks in your own file.**

## 2. Pick your next task automatically
1. Sync: `git switch develop && git pull`.
2. Run `python3 scripts/next-task.py <chirag|pavan|anshuman>`. It reads every task file and prints `NEXT: <id>` only when all of that task's dependencies are met.
   - Every task line ends with `(needs: …)`:
     - `C3` means that task is `[x]`, done and merged on `develop`;
     - `C8 started` means it is `[~]` or `[x]`;
     - `approval: Name` means a person must confirm first;
     - `none` means there is nothing to wait for.
   - **If it prints `BLOCKED`, stop.** Don't start a blocked task. Don't stub, mock or "temporarily" work around a missing dependency unless the task text explicitly tells you to. Don't edit another person's files to unblock yourself.
   - Instead, tell your human what you are waiting for (the script lists it), and run the script again after the next `git pull`.
   - If a task needs `approval: Name`, ask your human to get that confirmation before you start.
3. Claim it:
   - change `[ ]` to `[~] (<name>, feat/<task-id>-<slug>)` in your file;
   - commit only that line with message `chore(tasks): claim <task-id>`;
   - push to `develop`.
4. Create the branch: `git switch -c feat/<task-id>-<slug>`.
5. Do the steps in order: tests first, then the code, then run the service's whole test suite.
6. On your branch, mark the task `[x]` and push the branch. Open a PR into `develop` with `gh pr create --base develop`. Describe what you did and paste the test output.
7. Tell your human it's ready, then go back to step 1 for the next task.

## 3. Rules that apply to every task

**Secrets and data**
- **Never use Anthropic models or an `ANTHROPIC_API_KEY`.** Use Groq first, then Gemini and Mistral.
- Keys live in `.env` only. Never commit it, never print key values, never paste them into code or chat.
- Synthetic data only. No real names, phone numbers, Aadhaar or PAN numbers.

**What we show and claim**
- No hard-coded statistics. Every number on screen or in speech comes from stored data.
- No compliance claims ("RBI compliant", "zero hallucinations", "production-grade") anywhere. Judges score observable behaviour, and the rules say a prototype is not certified.

**The contract and the code**
- The **Shared contract** in `docs/superpowers/plans/2026-10-31-csm-voice-agent.md` is fixed. Don't rename endpoints, fields or enum values; ask the human to check with Anshuman first.
- **No repeated string literals for fixed vocabularies.** Route paths, endpoint paths, tool names, error codes, statuses, categories, outcomes, channels, roles and reference prefixes are enums or named constants, defined once and imported everywhere.
  - Python: a `StrEnum`, validated at the API boundary (unknown value gives 422).
  - Java: an `enum`.
  - TypeScript: a `const` object plus its derived union type (`export const Outcome = {...} as const; export type Outcome = typeof Outcome[keyof typeof Outcome]`).
  - One-off log lines, user-facing sentences and prompt text stay as plain strings.
- Every task comes with tests, and the suite stays green.

**Git**
- Never push to `main`. Never force-push a branch someone else uses. Don't rewrite history on `develop`.

## 4. Where things are

| Path | What |
|---|---|
| `docs/brief/problem-05.md` | What the judges test (scenarios, required intents, rules) |
| `docs/superpowers/specs/2026-10-31-csm-voice-agent-design.md` | The design |
| `docs/superpowers/plans/2026-10-31-csm-voice-agent.md` | The plan: shared contract and task index |
| `backend/simulator` | FastAPI bank simulator, port 8090 (Chirag) |
| `backend/voice` | Pipecat voice agent, port 7861 (Anshuman) |
| `backend/voice/eval` | Scenarios, utterances, audio renderer (Pavan) and harness (Anshuman) |
| `backend/api` | FastAPI system of record, port 8080: calls, transcripts, audit, Renewal Desk |
| `frontend` | React operator panel, port 5173 |

## 5. Running tests

| Service | Command |
|---|---|
| Simulator | `cd backend/simulator && python -m pytest -q` |
| Voice | `cd backend/voice && .venv/bin/pytest -q` |
| Core API | `cd backend/api && .venv/bin/pytest -q` |
| Frontend | `cd frontend && npm test && npx tsc --noEmit` |
