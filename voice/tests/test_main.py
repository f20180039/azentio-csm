import httpx
from fastapi.testclient import TestClient

from app import main
from app.api_client import RenewalsApi
from app.config import Settings


def client_with(handler) -> TestClient:
    main.state.api = RenewalsApi(Settings(), transport=httpx.MockTransport(handler))
    main.state.llm = None
    main.state.brains.clear()
    return TestClient(main.app)


def test_blank_text_turn_is_rejected():
    c = client_with(lambda r: httpx.Response(200, json={}))
    assert c.post("/v1/text-turn", json={"callId": "x", "text": "   "}).status_code == 400


def test_unknown_call_is_404():
    c = client_with(lambda r: httpx.Response(200, json={}))
    assert c.post("/v1/text-turn", json={"callId": "nope", "text": "hi"}).status_code == 404


def test_text_call_returns_greeting_and_creates_brain():
    seen = []

    def handler(r):
        seen.append((r.method, r.url.path))
        if r.method == "GET":
            return httpx.Response(200, json={"greeting": "Hello Meera", "holderName": "Meera"})
        return httpx.Response(200, json={})

    c = client_with(handler)
    resp = c.post("/v1/text-call", json={"callId": "abc"})
    assert resp.json() == {"greeting": "Hello Meera"}
    assert "abc" in main.state.brains
    assert ("POST", "/api/v1/renewals/calls/abc/turns") in seen


def test_text_call_unknown_call_is_404():
    c = client_with(lambda r: httpx.Response(404, json={"detail": "NOT_FOUND"}))
    assert c.post("/v1/text-call", json={"callId": "zzz"}).status_code == 404


def test_llm_failure_is_502():
    class Down:
        async def complete(self, messages, tools):
            raise httpx.ConnectError("down")

    c = client_with(lambda r: httpx.Response(200, json={}))
    from app.brain import CallBrain
    main.state.brains["k"] = CallBrain(Down(), main.state.api, "k", "SYS")
    assert c.post("/v1/text-turn", json={"callId": "k", "text": "hi"}).status_code == 502


def test_repeat_text_call_is_idempotent():
    turns = []

    def handler(r):
        if r.method == "GET":
            return httpx.Response(200, json={"greeting": "Hello Meera"})
        turns.append(r.url.path)
        return httpx.Response(200, json={})

    c = client_with(handler)
    first = c.post("/v1/text-call", json={"callId": "abc"}).json()
    brain = main.state.brains["abc"]
    second = c.post("/v1/text-call", json={"callId": "abc"}).json()
    assert first == second == {"greeting": "Hello Meera"}
    assert main.state.brains["abc"] is brain
    assert len(turns) == 1
