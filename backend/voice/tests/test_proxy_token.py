"""Tunnel guard with a proxy-only secret: a request through the tunnel reaches a non-public route only when the panel's
dev-server proxy added x-voice-proxy-token matching VOICE_PROXY_TOKEN. Without a configured token nothing changes."""
import pytest
from fastapi.testclient import TestClient
from loguru import logger
from starlette.websockets import WebSocketDisconnect

from app import main
from app.config import PROXY_TOKEN_MIN_CHARS, Settings, load_settings
from app.vocab import Route

TOKEN = "judges-only-" + "x" * (PROXY_TOKEN_MIN_CHARS - len("judges-only-"))
SHORT = "too-short-" + "x" * 5
LLM_STATUS = "/v1/llm/status"
TUNNEL = {"Cf-Connecting-Ip": "203.0.113.9", "X-Forwarded-For": "203.0.113.9"}
ECHO_WS = "/ws/test-only-proxy-echo"


def tunnelled(token: str | None = None) -> dict[str, str]:
    return TUNNEL | ({main.PROXY_TOKEN_HEADER.decode(): token} if token is not None else {})


@pytest.fixture
def client():
    def make(settings: Settings = Settings()) -> TestClient:
        main.state._settings = settings
        return TestClient(main.app)

    yield make
    main.state._settings = None


@pytest.fixture
def logs():
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    yield lines
    logger.remove(sink)


def test_tunnelled_request_without_token_is_refused(client):
    refused = {"detail": "LOCAL_ONLY"}
    r = client().get(LLM_STATUS, headers=tunnelled())  # no token configured
    assert r.status_code == 403 and r.json() == refused
    r = client().get(LLM_STATUS, headers=tunnelled(TOKEN))  # no token configured, header sent anyway
    assert r.status_code == 403 and r.json() == refused
    c = client(Settings(voice_proxy_token=TOKEN))
    assert c.get(LLM_STATUS, headers=tunnelled()).status_code == 403  # configured, header missing
    assert c.get(LLM_STATUS, headers=tunnelled("")).status_code == 403
    assert c.get(LLM_STATUS, headers=tunnelled(TOKEN[:-1] + "y")).status_code == 403  # wrong token
    assert c.get(LLM_STATUS, headers=tunnelled(TOKEN + "z")).status_code == 403  # longer token
    assert c.get(LLM_STATUS, headers=tunnelled(TOKEN)).json() != refused


def test_tunnelled_request_with_the_right_token_is_allowed(client):
    c = client(Settings(voice_proxy_token=TOKEN))
    r = c.get(LLM_STATUS, headers=tunnelled(TOKEN))
    assert r.status_code == 200 and "detail" not in r.json()
    r = c.get("/v1/eval/latest", headers={"Forwarded": "for=203.0.113.9;proto=https", main.PROXY_TOKEN_HEADER.decode(): TOKEN})
    assert r.status_code in (200, 404) and r.json().get("detail") != "LOCAL_ONLY"


def test_short_token_counts_as_unset(client, tmp_path, monkeypatch, logs):
    monkeypatch.delenv("VOICE_PROXY_TOKEN", raising=False)
    env = tmp_path / "voice.env"
    env.write_text(f"VOICE_PROXY_TOKEN={SHORT}\n")
    s = load_settings(env)
    assert s.voice_proxy_token == ""
    assert any("VOICE_PROXY_TOKEN" in line and "ignored" in line for line in logs)
    assert not any(SHORT in line for line in logs)
    assert SHORT not in repr(s)
    r = client(s).get(LLM_STATUS, headers=tunnelled(SHORT))
    assert r.status_code == 403 and r.json() == {"detail": "LOCAL_ONLY"}
    # a long enough token loads, from the environment first and from .env otherwise
    monkeypatch.setenv("VOICE_PROXY_TOKEN", TOKEN)
    s = load_settings(env)
    assert s.voice_proxy_token == TOKEN and TOKEN not in repr(s)
    monkeypatch.delenv("VOICE_PROXY_TOKEN")
    env.write_text(f"VOICE_PROXY_TOKEN={TOKEN}\n")
    assert load_settings(env).voice_proxy_token == TOKEN
    assert load_settings(None).voice_proxy_token == ""


def test_local_requests_are_unchanged(client):
    for settings in (Settings(), Settings(voice_proxy_token=TOKEN)):
        c = client(settings)
        assert c.get(LLM_STATUS).status_code == 200
        assert c.get(LLM_STATUS, headers={main.PROXY_TOKEN_HEADER.decode(): "whatever"}).status_code == 200


def test_public_paths_unchanged(client):
    for settings in (Settings(), Settings(voice_proxy_token=TOKEN)):
        c = client(settings)
        assert c.get(Route.HEALTH, headers=tunnelled()).status_code == 200
        r = c.post(f"{Route.TWILIO_TWIML}?callId=0", headers=tunnelled())
        assert r.status_code == 422 and r.json() != {"detail": "LOCAL_ONLY"}  # reached the route (callId is not a UUID)
        r = c.post(Route.TWILIO_SUPPORT_INCOMING, data={"CallSid": "CA1"}, headers=tunnelled())
        assert r.status_code == 403 and r.json() != {"detail": "LOCAL_ONLY"}  # reached the route (Twilio signature check)


def test_tunnelled_websocket_needs_the_token(client):
    @main.app.websocket(ECHO_WS)
    async def echo(ws: main.WebSocket):
        await ws.accept()
        await ws.send_text("reached")

    try:
        c = client(Settings(voice_proxy_token=TOKEN))
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect(ECHO_WS, headers=tunnelled()) as ws:
                ws.receive_text()
        assert e.value.code == 1008
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect(ECHO_WS, headers=tunnelled("wrong-" + TOKEN)) as ws:
                ws.receive_text()
        assert e.value.code == 1008
        with c.websocket_connect(ECHO_WS, headers=tunnelled(TOKEN)) as ws:
            assert ws.receive_text() == "reached"
        with pytest.raises(WebSocketDisconnect) as e:  # no token configured: the header alone opens nothing
            with client().websocket_connect(ECHO_WS, headers=tunnelled(TOKEN)) as ws:
                ws.receive_text()
        assert e.value.code == 1008
    finally:
        main.app.router.routes = [r for r in main.app.router.routes if getattr(r, "path", "") != ECHO_WS]


def test_the_token_is_never_logged(client, logs, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_PROXY_TOKEN", TOKEN)
    s = load_settings(None)
    c = client(s)
    c.get(LLM_STATUS, headers=tunnelled(TOKEN))
    c.get(LLM_STATUS, headers=tunnelled("wrong-" + TOKEN))
    c.get(LLM_STATUS, headers=tunnelled())
    assert not any(TOKEN in line for line in logs)
    assert TOKEN not in repr(s) and TOKEN not in str(s)
