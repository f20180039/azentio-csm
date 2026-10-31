import asyncio
import json

import httpx
import pytest

from app.intents import Intent, IntentResult, classify, rules_classify

KEY = "gk-intent-secret"


@pytest.mark.parametrize("text", [
    "When is my next EMI?",
    "How much do I need to pay next month?",
    "Tell me my next loan instalment.",
    "What's the due date for my personal loan?",
])
def test_repayment_phrasings(text):
    assert rules_classify(text).intents == [Intent.REPAYMENT]


@pytest.mark.parametrize("text, expected", [
    ("what's the weather in Bangalore", Intent.UNSUPPORTED),
    ("can you book me a flight", Intent.UNSUPPORTED),
    ("tell me a joke", Intent.UNSUPPORTED),
    ("transfer 5000 rupees to my friend", Intent.UNSUPPORTED),
    ("my number is 98765 00002", Intent.IDENTITY),
    ("my date of birth is 12/03/1988", Intent.IDENTITY),
    ("nine eight seven six five zero zero zero zero two", Intent.IDENTITY),
    ("send me my loan statement", Intent.SERVICE_REQUEST),
    ("status of SR-40102", Intent.SERVICE_REQUEST),
    ("documents for a vehicle loan", Intent.PRODUCT_INFO),
    ("my health claim status", Intent.INSURANCE),
    ("I want to talk to a person", Intent.HUMAN_AGENT),
    ("what is my savings account balance", Intent.ACCOUNT),
    ("what is the status of my loan application", Intent.LOAN_APPLICATION),
])
def test_single_intents(text, expected):
    assert rules_classify(text).intents == [expected]


def test_vague_issue_is_unclear():
    assert rules_classify("I have an issue with the thing from last time").intents == [Intent.UNCLEAR]
    assert rules_classify("").intents == [Intent.UNCLEAR]


def test_failed_transfer_is_complaint():
    assert Intent.COMPLAINT in rules_classify("money got debited but transfer failed").intents


def test_greeting_is_chitchat_only_when_alone():
    assert rules_classify("hello").intents == [Intent.CHITCHAT]
    assert rules_classify("ok thank you bye").intents == [Intent.CHITCHAT]
    assert rules_classify("hi, when is my EMI").intents == [Intent.REPAYMENT]


def test_multi_intent_in_order():
    result = rules_classify("status of my loan application and when is my first EMI")
    assert result.intents == [Intent.LOAN_APPLICATION, Intent.REPAYMENT]
    assert result.source == "rules"


def _llm(content: str | None = None, status: int = 200, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": "boom"})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})
    return httpx.MockTransport(handler)


def _classify(text, transport, history=None, api_key=KEY, timeout=1.5):
    return asyncio.run(classify(text, history or [], api_key=api_key, model="openai/gpt-oss-20b",
                                transport=transport, timeout=timeout))


def test_llm_result_drops_unknown_labels_and_sends_json_mode_with_history():
    seen = []
    history = [{"role": "user", "content": "when is my personal loan EMI"},
               {"role": "assistant", "content": "Your EMI is due on the 5th."}]
    transport = _llm(json.dumps({"intents": ["repayment", "BOGUS", "REPAYMENT"], "confidence": 0.9}), seen=seen)
    result = _classify("and the vehicle one?", transport, history)
    assert result == IntentResult([Intent.REPAYMENT], 0.9, "llm")
    body = json.loads(seen[0].content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == "openai/gpt-oss-20b"
    assert "personal loan EMI" in body["messages"][-1]["content"]
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"


def test_llm_only_unknown_labels_falls_back():
    result = _classify("When is my next EMI?", _llm(json.dumps({"intents": ["NOPE"], "confidence": 1})))
    assert result.source == "rules" and result.intents == [Intent.REPAYMENT]


def test_server_error_falls_back():
    result = _classify("When is my next EMI?", _llm(status=500))
    assert result.source == "rules" and result.intents == [Intent.REPAYMENT]


def test_bad_json_falls_back():
    assert _classify("When is my next EMI?", _llm("not json")).source == "rules"


def test_timeout_falls_back():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)
    assert _classify("When is my next EMI?", httpx.MockTransport(handler)).source == "rules"


def test_slow_llm_hits_overall_timeout():
    async def handler(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={})
    result = _classify("When is my next EMI?", httpx.MockTransport(handler), timeout=0.05)
    assert result.source == "rules"


def test_missing_key_falls_back_without_calling():
    seen = []
    result = _classify("When is my next EMI?", _llm("{}", seen=seen), api_key="")
    assert result.source == "rules" and not seen


def test_key_never_logged(caplog):
    from loguru import logger
    lines = []
    sink = logger.add(lines.append)
    try:
        _classify("When is my next EMI?", _llm(status=401))
    finally:
        logger.remove(sink)
    assert lines and not any(KEY in str(l) for l in lines)


def test_rules_fallback_on_pavans_labelled_utterances():
    """eval/utterances.csv: a greeting alongside a request is scored on the request (CHITCHAT is returned only alone)."""
    import csv
    from pathlib import Path

    rows = list(csv.DictReader((Path(__file__).parents[1] / "eval" / "utterances.csv").open(encoding="utf-8")))
    hits = 0
    for r in rows:
        want = set(r["intents"].split("|"))
        want = want - {"CHITCHAT"} if len(want) > 1 else want
        hits += want <= {str(i) for i in rules_classify(r["text"]).intents}
    assert len(rows) == 60 and hits >= 57, f"{hits}/60"
