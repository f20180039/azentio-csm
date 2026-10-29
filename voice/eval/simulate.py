"""Simulated-customer evaluation: an LLM plays each persona against the real voice agent over the text channel.

  cd voice && .venv/bin/python -m eval.simulate --per-persona 3
Needs the renewals API and the voice service running. Writes eval/out/latest.json and eval/out/report.md.
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Protocol

import httpx

from app.config import load_settings
from app.llm_chain import PROVIDERS

from . import report
from .personas import PERSONAS, Persona, SeedPolicy, customer_prompt, load_seed
from .scoring import score

GROQ_URL = f"{PROVIDERS['groq']}/chat/completions"

CUSTOMER_MODEL = "openai/gpt-oss-20b"
CUSTOMER_ATTEMPTS = 4
CUSTOMER_RESAMPLES = 3  # gpt-oss on Groq sometimes emits a tool-shaped turn (400 tool_use_failed)
MAX_RETRY_WAIT = 60.0
VOICE_ATTEMPTS = 3
VOICE_RETRY_WAIT = 45.0  # the agent model's per-minute token window
END = "[END]"
DAILY_LIMIT = "Groq daily limit"

Sleep = Callable[[float], Awaitable[None]]


class CustomerUnavailable(Exception):
    pass


class DailyLimitReached(Exception):
    """Groq's per-day quota is spent; nothing more can be learned today, so the run stops."""


def _is_daily_limit(resp: httpx.Response) -> bool:
    return resp.status_code == 429 and ("per day" in resp.text or "LLM_DAILY_LIMIT" in resp.text)


class Customer(Protocol):
    async def reply(self, messages: list[dict]) -> str: ...


def _retry_after(resp: httpx.Response, fallback: float) -> float:
    try:
        return min(max(float(resp.headers["retry-after"]), 0.0), MAX_RETRY_WAIT)
    except (KeyError, ValueError):
        return fallback


class GroqCustomer:
    def __init__(self, api_key: str, model: str = CUSTOMER_MODEL, transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Sleep = asyncio.sleep):
        self._model = model
        self._sleep = sleep
        self._client = httpx.AsyncClient(headers={"Authorization": f"Bearer {api_key}"}, timeout=60.0, transport=transport)

    async def reply(self, messages: list[dict]) -> str:
        body = {"model": self._model, "messages": messages, "reasoning_effort": "low"}
        resamples = 0
        attempt = 0
        while True:
            try:
                resp = await self._client.post(GROQ_URL, json=body)
            except httpx.HTTPError as e:
                raise CustomerUnavailable(f"customer LLM unreachable: {e!r}") from e
            if _is_daily_limit(resp):
                raise DailyLimitReached(f"{DAILY_LIMIT} (customer model)")
            if resp.status_code in (429, 503) and attempt < CUSTOMER_ATTEMPTS - 1:
                attempt += 1
                await self._sleep(_retry_after(resp, 10.0 * attempt))
                continue
            if resp.status_code == 400 and resamples < CUSTOMER_RESAMPLES:
                resamples += 1
                continue
            if resp.status_code >= 400:
                try:
                    err = resp.json()["error"]
                    reason = f"{err.get('code')}: {err.get('message')}"[:160]
                except (ValueError, KeyError, TypeError, AttributeError):
                    reason = resp.reason_phrase
                raise CustomerUnavailable(f"customer LLM returned HTTP {resp.status_code} ({reason})")
            text = (resp.json()["choices"][0]["message"].get("content") or "").strip()
            if not text:
                raise CustomerUnavailable("customer LLM returned an empty reply")
            return text

    async def aclose(self) -> None:
        await self._client.aclose()


def pick_policies(queue: list[dict], known: set[str], n: int) -> list[str]:
    ids = [q["policyId"] for q in queue if q["route"] == "AGENT_CALL" and q["policyId"] in known]
    if not ids:
        raise SystemExit("no AGENT_CALL policies in the queue")
    return [ids[i % len(ids)] for i in range(n)]


async def _json(resp_coro) -> dict | list:
    resp = await resp_coro
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} from {resp.request.method} {resp.request.url.path}: {resp.text[:200]}")
    return resp.json()


TOOL_EVENT_PREFIXES = ("tool.", "rule.", "identity.")


async def _tool_events(api: httpx.AsyncClient, call_id: str) -> int:
    audit = await _json(api.get(f"/api/v1/cases/{call_id}/audit"))
    return sum(e["action"].startswith(TOOL_EVENT_PREFIXES) for e in audit)


async def _text_turn(api: httpx.AsyncClient, voice: httpx.AsyncClient, call_id: str, text: str, sleep: Sleep,
                     result: dict) -> dict:
    """A failed turn is retried with the same line, but only if the audit shows no tool ran during it:
    re-running tools would repeat refused requests and inflate the blocked counts."""
    before = await _tool_events(api, call_id)
    for attempt in range(VOICE_ATTEMPTS):
        resp = await voice.post("/v1/text-turn", json={"callId": call_id, "text": text})
        if _is_daily_limit(resp):
            raise DailyLimitReached(f"{DAILY_LIMIT} (agent model)")
        if resp.status_code < 500 or attempt == VOICE_ATTEMPTS - 1:
            break
        if await _tool_events(api, call_id) != before:
            raise RuntimeError(f"HTTP {resp.status_code} from voice /v1/text-turn; no retry after tools ran")
        await sleep(VOICE_RETRY_WAIT)
        result["retried_turns"] += 1
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} from voice /v1/text-turn: {resp.text[:200]}")
    return resp.json()


async def run_conversation(persona: Persona, policy_id: str, seed: dict[str, SeedPolicy], api: httpx.AsyncClient,
                           voice: httpx.AsyncClient, customer: Customer, max_turns: int, turn_gap: float,
                           sleep: Sleep = asyncio.sleep) -> dict:
    policy = seed[policy_id]
    result: dict = {"persona": persona.name, "expect": persona.expect, "policyId": policy_id,
                    "holderName": policy.holder_name, "callId": None, "outcome": None, "expected_met": None,
                    "blocked_requests": 0, "identity_failures": 0, "refusals": 0, "rule_breaks": [],
                    "leak_before_verify": [], "spoken_discount_claims": [], "turns": 0, "hit_max_turns": False,
                    "daily_limit": False, "retried_turns": 0, "models": {}, "error": None, "transcript": []}
    turns = 0
    messages = [{"role": "system", "content": customer_prompt(persona, policy)}]
    try:
        started = await _json(api.post("/api/v1/renewals/calls", json={"policyId": policy_id, "simulated": True}))
        call_id = result["callId"] = started["callId"]
        greeting = (await _json(voice.post("/v1/text-call", json={"callId": call_id})))["greeting"]
        messages.append({"role": "user", "content": greeting})
        for n in range(max_turns):
            if n:
                await sleep(turn_gap)
            line = await customer.reply(messages)
            if line.strip() == END:
                break
            line = line.replace(END, "").strip()
            messages.append({"role": "assistant", "content": line})
            turns += 1
            turn = await _text_turn(api, voice, call_id, line, sleep, result)
            model = turn.get("model") or "unknown"
            result["models"][model] = result["models"].get(model, 0) + 1
            messages.append({"role": "user", "content": turn["reply"] or "..."})
            tools = {t["name"] for t in turn["toolCalls"] if "error" not in (t.get("result") or {})}
            if tools & {"end_call", "handoff_to_human"}:
                break
        else:
            result["hit_max_turns"] = True
    except DailyLimitReached as e:
        result["daily_limit"] = True
        result["error"] = f"{type(e).__name__}: {e}"[:300]
    except Exception as e:  # one bad conversation must not stop the run
        result["error"] = f"{type(e).__name__}: {e}"[:300]
    if result["callId"]:
        try:
            await _json(api.post(f"/api/v1/renewals/calls/{result['callId']}/end"))
            call = await _json(api.get(f"/api/v1/renewals/calls/{result['callId']}"))
            audit = await _json(api.get(f"/api/v1/cases/{result['callId']}/audit"))
        except Exception as e:
            result["error"] = result["error"] or f"{type(e).__name__}: {e}"[:300]
        else:
            result.update(score(persona.name, call, audit, policy.renewal_premium), turns=turns)
            result["transcript"] = [{"role": t["role"], "text": t["text"]} for t in call.get("transcript") or []]
            result["audit"] = [e["action"] for e in audit]
    if result["error"]:
        result["expected_met"] = None
    return result


async def run_eval(names: list[str], per_persona: int, api: httpx.AsyncClient, voice: httpx.AsyncClient,
                   customer: Customer, seed: dict[str, SeedPolicy], max_turns: int, turn_gap: float,
                   sleep: Sleep = asyncio.sleep, log: Callable[[str], None] = print) -> list[dict]:
    queue = await _json(api.get("/api/v1/renewals/queue"))
    policies = iter(pick_policies(queue, set(seed), len(names) * per_persona))
    out = []
    for name in names:
        for i in range(per_persona):
            if out:
                await sleep(turn_gap)
            r = await run_conversation(PERSONAS[name], next(policies), seed, api, voice, customer, max_turns,
                                       turn_gap, sleep)
            status = r["error"] or f"{r['outcome']} expected_met={r['expected_met']}"
            log(f"[{len(out) + 1}] {name} #{i + 1} {r['policyId']} turns={r['turns']} {status}")
            out.append(r)
            if r["daily_limit"]:
                log(f"stopping: {DAILY_LIMIT}")
                return out
    return out


def finish(convs: list[dict], meta: dict, out_dir: Path) -> int:
    """Writes the report; returns the process exit code (non-zero when the run stopped at the daily limit)."""
    partial = any(c.get("daily_limit") for c in convs)
    if partial:
        meta = {**meta, "partial": DAILY_LIMIT}
    rep = report.summarise(convs, meta)
    json_path, md_path = report.write(rep, out_dir)
    t = rep["totals"]
    print(f"{t['conversations']} conversations, {t['errors']} errors, rule breaks {t['rule_breaks']}, "
          f"leaks {t['leaks']}, spoken discount claims {t['spoken_discount_claims']}, median turns {t['median_turns']}"
          + (f" (partial: {DAILY_LIMIT})" if partial else ""))
    print(f"wrote {json_path} and {md_path}")
    return 3 if partial else 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--per-persona", type=int, default=3)
    ap.add_argument("--turn-gap", type=float, default=20.0, help="seconds between turns; Groq free tier is 8k tokens/min")
    ap.add_argument("--max-turns", type=int, default=12)
    ap.add_argument("--api", default="http://localhost:8080")
    ap.add_argument("--voice", default="http://localhost:7861")
    ap.add_argument("--personas", default=",".join(PERSONAS))
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "out")
    return ap.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    names = [n.strip() for n in args.personas.split(",") if n.strip()]
    unknown = set(names) - set(PERSONAS)
    if unknown:
        raise SystemExit(f"unknown personas: {sorted(unknown)}")
    env = Path(__file__).resolve().parents[2] / ".env"
    settings = load_settings(env if env.exists() else None)
    if not settings.groq_api_key:
        raise SystemExit("GROQ_API_KEY is not set")
    started = datetime.now(timezone.utc)
    customer = GroqCustomer(settings.groq_api_key)
    async with httpx.AsyncClient(base_url=args.api.rstrip("/"), auth=("analyst", "analyst"), timeout=30) as api, \
            httpx.AsyncClient(base_url=args.voice.rstrip("/"), timeout=180) as voice:
        convs = await run_eval(names, args.per_persona, api, voice, customer, load_seed(), args.max_turns,
                               args.turn_gap, log=lambda s: print(s, flush=True))
    await customer.aclose()
    meta = {"started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "per_persona": args.per_persona, "max_turns": args.max_turns, "turn_gap_s": args.turn_gap,
            "customer_model": CUSTOMER_MODEL, "agent_model": ", ".join(l.name for l in settings.llm_chain)}
    return finish(convs, meta, args.out)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
