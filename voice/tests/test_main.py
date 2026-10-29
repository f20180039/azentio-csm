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


def test_offer_without_call_id_is_400():
    c = client_with(lambda r: httpx.Response(200, json={}))
    resp = c.post("/api/offer", json={"sdp": "v=0", "type": "offer", "requestData": {}})
    assert resp.status_code == 400


def test_health():
    c = client_with(lambda r: httpx.Response(200, json={}))
    assert c.get("/health").json() == {"status": "ok"}


def test_second_offer_for_a_live_call_is_409():
    c = client_with(lambda r: httpx.Response(200, json={}))
    main.state.live_calls["busy"] = "pc-1"
    try:
        body = {"sdp": "v=0", "type": "offer", "requestData": {"callId": "busy"}}
        resp = c.post("/api/offer", json=body)
        assert resp.status_code == 409
        assert resp.json()["detail"] == "CALL_IN_PROGRESS"
    finally:
        main.state.live_calls.clear()


def test_call_slot_is_freed_when_the_session_ends(monkeypatch):
    import pipecat.pipeline.runner as runner_mod

    from app import pipeline

    class FakeHandler:
        async def handle_web_request(self, request, callback):
            class Conn:
                async def disconnect(self):
                    pass

            await callback(Conn())
            assert main.state.live_calls == {"c1": None}
            return {"sdp": "answer", "type": "answer", "pc_id": "pc-1"}

    class FakeRunner:
        def __init__(self, **_):
            pass

        async def run(self, task):
            assert main.state.live_calls == {"c1": "pc-1"}

    async def fake_build(settings, call_id, transport):
        return object()

    monkeypatch.setattr(pipeline, "build_pipeline", fake_build)
    monkeypatch.setattr(runner_mod, "PipelineRunner", FakeRunner)
    monkeypatch.setattr("pipecat.transports.smallwebrtc.transport.SmallWebRTCTransport", lambda **_: None)
    c = client_with(lambda r: httpx.Response(200, json={}))
    main.state.webrtc = FakeHandler()
    try:
        body = {"sdp": "v=0", "type": "offer", "requestData": {"callId": "c1"}}
        assert c.post("/api/offer", json=body).status_code == 200
        assert main.state.live_calls == {}
        assert c.post("/api/offer", json=body).status_code == 200
    finally:
        main.state.webrtc = None
        main.state.live_calls.clear()


def test_cors_preflight_allows_only_the_web_origin():
    c = client_with(lambda r: httpx.Response(200, json={}))
    ok = c.options(
        "/api/offer",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = c.options(
        "/api/offer",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in other.headers


def test_cors_preflight_allows_patch_for_ice_trickle():
    c = client_with(lambda r: httpx.Response(200, json={}))
    r = c.options(
        "/api/offer",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200
    assert "PATCH" in r.headers["access-control-allow-methods"]


def test_patch_unknown_peer_connection_is_404():
    from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequestHandler

    c = client_with(lambda r: httpx.Response(200, json={}))
    main.state.webrtc = None
    body = {"pc_id": "nope", "candidates": [{"candidate": "", "sdp_mid": "0", "sdp_mline_index": 0}]}
    assert c.patch("/api/offer", json=body).status_code == 404
    main.state.webrtc = SmallWebRTCRequestHandler()
    assert c.patch("/api/offer", json=body).status_code == 404
    main.state.webrtc = None


def test_patch_known_peer_connection_reaches_the_handler():
    seen = []

    class FakeHandler:
        async def handle_patch_request(self, request):
            seen.append(request)

    c = client_with(lambda r: httpx.Response(200, json={}))
    main.state.webrtc = FakeHandler()
    body = {"pc_id": "pc-1", "candidates": [{"candidate": "candidate:1 1 udp 1 1.2.3.4 5 typ host", "sdp_mid": "0", "sdp_mline_index": 0}]}
    r = c.patch("/api/offer", json=body)
    main.state.webrtc = None
    assert r.status_code == 200
    assert seen[0].pc_id == "pc-1" and seen[0].candidates[0].sdp_mline_index == 0
