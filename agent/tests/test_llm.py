import json

import pytest

from app.explain import ExplainRequest, explain
from app.jsonout import complete_structured
from app.llm.gateway import Gateway, LlmRequest, LlmResponse, MockProvider, ProviderError
from app.schemas.demo import DemoFields

GOOD = {"document_kind": "invoice", "parties": ["A"], "dates": ["01/01/2026"],
        "amounts": [{"value": 10.0, "currency": "INR", "context": "x"}]}


class Failing:
    name = "broken"

    def complete(self, req: LlmRequest) -> LlmResponse:
        raise ProviderError("down")


class Scripted:
    """Returns queued outputs in order, to simulate a model that needs repair."""

    name = "scripted"

    def __init__(self, outputs: list[str]):
        self.outputs = outputs
        self.requests: list[LlmRequest] = []

    def complete(self, req: LlmRequest) -> LlmResponse:
        self.requests.append(req)
        return LlmResponse(text=self.outputs.pop(0), provider=self.name, model="scripted")


def _req() -> LlmRequest:
    return LlmRequest("extract", "sys", "user", mock_response=lambda: json.dumps(GOOD))


def test_gateway_falls_back_to_mock():
    resp = Gateway([Failing(), MockProvider()]).complete(_req())
    assert resp.provider == "mock"
    assert resp.attempts == ["broken:down"]


def test_gateway_raises_when_every_provider_fails():
    with pytest.raises(ProviderError):
        Gateway([Failing()]).complete(_req())


def test_valid_output_needs_no_repair():
    model = Scripted([json.dumps(GOOD)])
    result = complete_structured(Gateway([model]), DemoFields, "extract", "sys", "user", lambda: "")
    assert result.error is None and result.value.document_kind == "invoice"
    assert len(model.requests) == 1


def test_invalid_output_is_repaired_once():
    bad = json.dumps({**GOOD, "amounts": [{"value": "ten", "currency": "INR", "context": "x"}]})
    model = Scripted([f"Sure! ```json\n{bad}\n```", json.dumps(GOOD)])
    result = complete_structured(Gateway([model]), DemoFields, "extract", "sys", "user", lambda: "")
    assert result.error is None
    assert len(model.requests) == 2
    assert "rejected" in model.requests[1].user


def test_output_still_invalid_after_repair_returns_error():
    model = Scripted(["not json", json.dumps({"document_kind": "x", "extra": 1})])
    result = complete_structured(Gateway([model]), DemoFields, "extract", "sys", "user", lambda: "")
    assert result.value is None and "validation" in result.error


def test_explain_drops_unverifiable_quotes():
    req = ExplainRequest(
        case_type="demo",
        findings=[
            {"id": "f1", "rule_id": "R1", "title": "ICU days", "evidence": []},
            {"id": "f2", "rule_id": "R2", "title": "Stent", "evidence": []},
            {"id": "f3", "rule_id": "R3", "title": "No support", "evidence": []},
        ],
        pages=[{"document_id": "d1", "page": 1, "text": "Shifted to ward on day 2. DES deployed."}],
    )
    output = {
        "summary": "s",
        "notes": [
            # cited on the wrong page but present on page 1: accepted and corrected
            {"finding_id": "f1", "note": "n", "quotes": [{"document_id": "d1", "page": 3, "text": "shifted to ward on day 2"}]},
            {"finding_id": "f2", "note": "n", "quotes": [{"document_id": "d1", "page": 1, "text": "two stents deployed"}]},
            {"finding_id": "f3", "note": "n", "quotes": []},
            {"finding_id": "ghost", "note": "n", "quotes": [{"document_id": "d1", "page": 1, "text": "DES deployed"}]},
        ],
    }
    result = explain(req, Gateway([Scripted([json.dumps(output)])]))
    assert [n["finding_id"] for n in result["notes"]] == ["f1"]
    assert result["notes"][0]["quotes"][0]["page"] == 1
    assert {d["finding_id"]: d["reason"] for d in result["dropped"]} == {
        "f2": "quote_not_found", "f3": "no_quote", "ghost": "unknown_finding"}


class Counting(Failing):
    def __init__(self):
        self.calls = 0

    def complete(self, req: LlmRequest) -> LlmResponse:
        self.calls += 1
        return super().complete(req)


def test_failed_provider_cools_down_then_returns():
    now = [0.0]
    broken, mock = Counting(), MockProvider()
    gw = Gateway([broken, mock], cooldown_s=30, clock=lambda: now[0])
    gw.complete(_req())
    assert gw._ordered()[0] is mock
    now[0] = 31
    assert gw._ordered()[0] is broken


def test_cooling_providers_are_still_tried_last():
    broken = Counting()
    gw = Gateway([broken], cooldown_s=30, clock=lambda: 0.0)
    for _ in range(2):
        with pytest.raises(ProviderError):
            gw.complete(_req())
    assert broken.calls == 2


def _compat(handler, key="k"):
    import httpx
    from app.config import CompatProvider, Settings
    from app.llm.openai_compat_provider import OpenAICompatProvider

    settings = Settings(compat={"groq": CompatProvider(key, "small", "big")})
    return OpenAICompatProvider("groq", settings, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_compat_provider_parses_reply_and_picks_model_by_purpose():
    import httpx

    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer k"
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}],
                                         "usage": {"prompt_tokens": 7, "completion_tokens": 2}})

    resp = _compat(handler).complete(LlmRequest("explain", "sys", "user", mock_response=lambda: ""))
    assert (resp.provider, resp.model, resp.input_tokens) == ("groq", "big", 7)
    assert seen["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("status", [429, 500])
def test_compat_provider_errors_become_provider_errors(status):
    import httpx

    provider = _compat(lambda r: httpx.Response(status, text="nope"))
    with pytest.raises(ProviderError, match=f"HTTP {status}"):
        provider.complete(_req())


def test_compat_provider_without_key_fails_fast():
    import httpx

    def handler(request):
        raise AssertionError("must not call the network without a key")

    with pytest.raises(ProviderError, match="no API key"):
        _compat(handler, key="").complete(_req())
