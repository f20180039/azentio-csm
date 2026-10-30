import asyncio
import base64
import json
import time
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from loguru import logger
from starlette.websockets import WebSocketDisconnect

from app import main, phone
from app.api_client import RenewalsApi
from app.config import Settings, load_settings

CALL = "55555555-5555-5555-5555-555555555555"
OTHER = "66666666-6666-6666-6666-666666666666"
OTHER2 = "88888888-8888-8888-8888-888888888888"
SID = "AC" + "1" * 32
TOKEN = "tok-very-secret-value"
FROM = "+15005550006"
ALLOWED = ("+919812344417", "+14155550123")
BASE = "https://demo-tunnel.trycloudflare.com"

CONFIGURED = Settings(
    twilio_account_sid=SID,
    twilio_auth_token=TOKEN,
    twilio_from=FROM,
    twilio_allowed_to=ALLOWED,
    public_base_url=BASE,
)


ENDED = "77777777-7777-7777-7777-777777777777"


def renewals(r: httpx.Request) -> httpx.Response:
    if r.method == "GET" and r.url.path.endswith(CALL):
        return httpx.Response(200, json={"greeting": "Hello Meera", "outcome": None})
    if r.method == "GET" and r.url.path.endswith(ENDED):
        return httpx.Response(200, json={"greeting": "Hello Meera", "outcome": "NO_DECISION"})
    if r.method == "GET" and r.url.path.endswith(OTHER2):
        return httpx.Response(200, json={"greeting": "Hello Ravi", "outcome": None})
    return httpx.Response(404, json={"detail": "NOT_FOUND"})


@pytest.fixture
def client():
    def make(settings: Settings = CONFIGURED, twilio=None, tunnel=None) -> TestClient:
        main.state._settings = settings
        main.state.api = RenewalsApi(Settings(), transport=httpx.MockTransport(renewals))
        main.state.twilio_transport = httpx.MockTransport(twilio or (lambda r: httpx.Response(201, json={"sid": "CA1"})))
        main.state.tunnel_transport = httpx.MockTransport(tunnel or (lambda r: httpx.Response(200, json={"status": "ok"})))
        return TestClient(main.app)

    yield make
    main.state._settings = None
    main.state.api = None
    main.state.twilio_transport = None
    main.state.tunnel_transport = None
    main.state.live_calls.clear()
    main.state.phone_pending.clear()


@pytest.fixture
def logs():
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    yield lines
    logger.remove(sink)


# ---- pure helpers -------------------------------------------------------------


def test_mask_shows_country_code_and_last_four_only():
    assert phone.mask("+919812344417") == "+91 ••••• •4417"
    assert phone.mask("+14155550123") == "+1 ••••• •0123"


def test_twiml_streams_to_the_public_wss_url_with_the_call_id():
    xml = phone.twiml(BASE + "/", CALL)
    assert '<Stream url="wss://demo-tunnel.trycloudflare.com/ws/twilio">' in xml
    assert f'<Parameter name="callId" value="{CALL}"/>' in xml
    assert xml.startswith("<Response><Connect>") and xml.endswith("</Connect></Response>")


def test_twiml_escapes_the_url():
    assert "&amp;" in phone.twiml("https://x.example/a?b=1&c=2", CALL)


def test_parse_start_reads_twilio_start_message():
    msg = {
        "event": "start",
        "streamSid": "MZ1",
        "start": {"streamSid": "MZ1", "callSid": "CA1", "customParameters": {"callId": CALL}},
    }
    assert phone.parse_start(msg) == phone.StreamStart(stream_sid="MZ1", call_sid="CA1", call_id=CALL)


@pytest.mark.parametrize(
    "msg",
    [
        {"event": "connected"},
        {"event": "start", "start": {"callSid": "CA1", "customParameters": {"callId": CALL}}},
        {"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1", "customParameters": {"callId": "../x"}}},
        {"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA1", "customParameters": {}}},
    ],
)
def test_parse_start_rejects_bad_messages(msg):
    with pytest.raises(ValueError):
        phone.parse_start(msg)


def test_dial_posts_the_twilio_calls_request_with_basic_auth(logs):
    seen: list[httpx.Request] = []

    def twilio(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return httpx.Response(201, json={"sid": "CA42", "status": "queued"})

    sid = asyncio.run(phone.dial(CONFIGURED, CALL, "+919812344417", transport=httpx.MockTransport(twilio)))
    assert sid == "CA42"
    (r,) = seen
    assert r.method == "POST"
    assert str(r.url) == f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Calls.json"
    assert r.headers["authorization"] == "Basic " + base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    form = {k: v[0] for k, v in parse_qs(r.content.decode()).items()}
    assert form["To"] == "+919812344417" and form["From"] == FROM
    assert "Twiml" not in form  # trial accounts refuse inline TwiML
    assert form["Url"] == f"{BASE}/twilio/twiml?callId={CALL}" and form["Method"] == "POST"
    assert not any(TOKEN in line for line in logs)


def test_dial_failure_carries_twilio_message_but_never_the_token(logs):
    def twilio(r):
        return httpx.Response(400, json={"code": 21219, "message": "The number is unverified."})

    with pytest.raises(phone.DialError) as e:
        asyncio.run(phone.dial(CONFIGURED, CALL, "+919812344417", transport=httpx.MockTransport(twilio)))
    assert "unverified" in str(e.value) and TOKEN not in str(e.value)
    assert not any(TOKEN in line for line in logs)


# ---- config -------------------------------------------------------------------


def test_twilio_settings_load_and_the_token_stays_out_of_repr(tmp_path, monkeypatch):
    for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "TWILIO_ALLOWED_TO", "PUBLIC_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    env = tmp_path / "v.env"
    env.write_text(
        f"TWILIO_ACCOUNT_SID={SID}\nTWILIO_AUTH_TOKEN={TOKEN}\nTWILIO_FROM={FROM}\n"
        f"TWILIO_ALLOWED_TO=+91 98123 44417, +14155550123,\nPUBLIC_BASE_URL={BASE}/\n"
    )
    s = load_settings(env)
    assert (s.twilio_account_sid, s.twilio_auth_token, s.twilio_from) == (SID, TOKEN, FROM)
    assert s.twilio_allowed_to == ALLOWED
    assert s.public_base_url == BASE
    assert TOKEN not in repr(s)
    assert phone.configured(s)
    assert not phone.configured(Settings())


# ---- HTTP endpoints -----------------------------------------------------------


def test_allowed_reports_not_configured_cleanly(client):
    r = client(Settings()).get("/v1/phone/allowed")
    assert r.status_code == 200
    assert r.json() == {"configured": False, "numbers": []}


def test_allowed_lists_masked_numbers_only(client):
    body = client().get("/v1/phone/allowed").json()
    assert body == {
        "configured": True,
        "numbers": [{"id": "0", "masked": "+91 ••••• •4417"}, {"id": "1", "masked": "+1 ••••• •0123"}],
    }
    assert "9812344417" not in json.dumps(body)


def test_phone_call_to_a_number_off_the_allow_list_is_403(client):
    hits = []
    c = client(twilio=lambda r: hits.append(r) or httpx.Response(201, json={"sid": "CA1"}))
    for body in ({"callId": CALL, "to": "+919999999999"}, {"callId": CALL, "numberId": "7"}):
        r = c.post("/v1/phone-call", json=body)
        assert r.status_code == 403 and r.json()["detail"] == "NUMBER_NOT_ALLOWED"
    assert hits == []


def test_phone_call_without_credentials_is_503(client):
    s = Settings(twilio_allowed_to=ALLOWED)
    r = client(s).post("/v1/phone-call", json={"callId": CALL, "to": "+919812344417"})
    assert r.status_code == 503 and r.json()["detail"] == "PHONE_NOT_CONFIGURED"


def test_phone_call_with_no_allow_list_is_503_not_403(client):
    r = client(Settings()).post("/v1/phone-call", json={"callId": CALL, "to": "+919812344417"})
    assert r.status_code == 503 and r.json()["detail"] == "PHONE_NOT_CONFIGURED"


@pytest.mark.parametrize("junk", ["abc", "-1", "１", "0x1", ""])
def test_phone_call_with_a_junk_number_id_is_400(client, junk):
    r = client().post("/v1/phone-call", json={"callId": CALL, "numberId": junk})
    assert r.status_code == 400


def test_phone_call_for_an_ended_call_is_409_and_dials_nothing(client):
    hits = []
    c = client(twilio=lambda r: hits.append(r) or httpx.Response(201, json={"sid": "CA1"}))
    r = c.post("/v1/phone-call", json={"callId": ENDED, "numberId": "0"})
    assert r.status_code == 409 and r.json()["detail"] == "CALL_ENDED"
    assert hits == []


def test_only_one_phone_dial_at_a_time_across_calls(client):
    c = client()
    assert c.post("/v1/phone-call", json={"callId": CALL, "numberId": "0"}).status_code == 200
    r = c.post("/v1/phone-call", json={"callId": OTHER2, "numberId": "1"})
    assert r.status_code == 409 and r.json()["detail"] == "PHONE_BUSY"
    main.state.phone_pending.clear()
    main.state.live_calls[CALL] = "twilio:CA77"
    r = c.post("/v1/phone-call", json={"callId": OTHER2, "numberId": "1"})
    assert r.status_code == 409 and r.json()["detail"] == "PHONE_BUSY"
    main.state.live_calls[CALL] = "pc-1"
    assert c.post("/v1/phone-call", json={"callId": OTHER2, "numberId": "1"}).status_code == 200


def test_phone_call_for_a_live_call_is_409(client):
    c = client()
    main.state.live_calls[CALL] = "pc-1"
    r = c.post("/v1/phone-call", json={"callId": CALL, "numberId": "0"})
    assert r.status_code == 409 and r.json()["detail"] == "CALL_IN_PROGRESS"


def test_phone_call_for_an_unknown_call_is_404_and_dials_nothing(client):
    hits = []
    c = client(twilio=lambda r: hits.append(r) or httpx.Response(201, json={"sid": "CA1"}))
    assert c.post("/v1/phone-call", json={"callId": OTHER, "numberId": "0"}).status_code == 404
    assert hits == []


def test_phone_call_dials_and_holds_the_slot_until_the_stream_arrives(client, logs):
    seen = []
    c = client(twilio=lambda r: seen.append(r) or httpx.Response(201, json={"sid": "CA77"}))
    r = c.post("/v1/phone-call", json={"callId": CALL, "numberId": "0"})
    assert r.status_code == 200 and r.json() == {"status": "dialling"}
    assert parse_qs(seen[0].content.decode())["To"] == ["+919812344417"]
    assert main.state.phone_pending[CALL][0] == "CA77"
    again = c.post("/v1/phone-call", json={"callId": CALL, "numberId": "0"})
    assert again.status_code == 409
    assert TOKEN not in r.text and not any(TOKEN in line for line in logs)


def test_phone_call_twilio_failure_is_502_and_frees_the_slot(client):
    c = client(twilio=lambda r: httpx.Response(400, json={"code": 21219, "message": "The number is unverified."}))
    r = c.post("/v1/phone-call", json={"callId": CALL, "to": "+919812344417"})
    assert r.status_code == 502 and "unverified" in r.json()["detail"] and TOKEN not in r.text
    assert CALL not in main.state.phone_pending


def test_mask_numbers_masks_every_full_number_in_a_text():
    text = "Twilio 400 21219: The number +919812344417 is unverified; From +15005550006."
    out = phone.mask_numbers(text)
    assert "9812344417" not in out and "5005550006" not in out
    assert "+91 ••••• •4417" in out and "21219" in out


def test_phone_call_twilio_error_never_carries_the_full_number(client, logs):
    msg = "The number +919812344417 is unverified. Trial accounts may only make calls to verified numbers."
    c = client(twilio=lambda r: httpx.Response(400, json={"code": 21219, "message": msg}))
    r = c.post("/v1/phone-call", json={"callId": CALL, "numberId": "0"})
    assert r.status_code == 502
    assert "9812344417" not in r.text and "•4417" in r.json()["detail"] and "21219" in r.json()["detail"]
    assert not any("9812344417" in line for line in logs)


def test_phone_call_checks_the_tunnel_first_and_dials_nothing_when_it_is_down(client):
    hits, probes = [], []

    def tunnel(r):
        probes.append(str(r.url))
        raise httpx.ConnectTimeout("no route", request=r)

    c = client(twilio=lambda r: hits.append(r) or httpx.Response(201, json={"sid": "CA1"}), tunnel=tunnel)
    r = c.post("/v1/phone-call", json={"callId": CALL, "numberId": "0"})
    assert r.status_code == 503 and r.json()["detail"] == "TUNNEL_DOWN"
    assert probes == [BASE + "/health"] and hits == []
    assert main.state.phone_pending == {}
    main.state.tunnel_transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ok"}))
    assert c.post("/v1/phone-call", json={"callId": CALL, "numberId": "0"}).status_code == 200


@pytest.mark.parametrize("answer", [httpx.Response(502, text="Bad gateway"), httpx.Response(200, text="<html>tunnel</html>"),
                                    httpx.Response(530, json={"status": "ok"})])
def test_a_tunnel_that_does_not_reach_this_service_is_down(client, answer):
    c = client(tunnel=lambda r: answer)
    r = c.post("/v1/phone-call", json={"callId": CALL, "numberId": "0"})
    assert r.status_code == 503 and r.json()["detail"] == "TUNNEL_DOWN"
    assert main.state.phone_pending == {}


def test_tunnel_check_uses_a_two_second_timeout(monkeypatch):
    seen = {}
    real = httpx.AsyncClient

    def spy(*a, **kw):
        seen["timeout"] = kw.get("timeout")
        return real(*a, **kw)

    monkeypatch.setattr(phone.httpx, "AsyncClient", spy)
    ok = asyncio.run(phone.tunnel_up(BASE, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ok"}))))
    assert ok and seen["timeout"] == 2.0


def test_a_stale_pending_dial_does_not_block_a_new_one(client):
    c = client()
    main.state.phone_pending[CALL] = ("CA-old", time.monotonic() - phone.PENDING_TTL_SECS - 1)
    assert c.post("/v1/phone-call", json={"callId": CALL, "numberId": "0"}).status_code == 200


def test_twiml_endpoint_serves_xml_for_a_pending_call_only(client):
    c = client()
    assert c.post(f"/twilio/twiml?callId={CALL}").status_code == 404
    main.state.phone_pending[CALL] = ("CA1", time.monotonic())
    r = c.post(f"/twilio/twiml?callId={CALL}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert r.text == phone.twiml(BASE, CALL)


# ---- WS /ws/twilio --------------------------------------------------------------


def start_msg(call_id=CALL, call_sid="CA1"):
    return {
        "event": "start",
        "sequenceNumber": "1",
        "start": {"streamSid": "MZ1", "callSid": call_sid, "accountSid": SID, "customParameters": {"callId": call_id}},
        "streamSid": "MZ1",
    }


def ws_rejects(c: TestClient, msg) -> int:
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})
        ws.send_json(msg)
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
    return e.value.code


@pytest.fixture
def fake_runtime(monkeypatch):
    built = []

    async def fake_build(settings, call_id, transport, chain=None, audio_sample_rate=None):
        built.append((call_id, transport, audio_sample_rate))
        assert main.state.live_calls.get(call_id) == "twilio:CA1"
        return object()

    class FakeRunner:
        def __init__(self, **_):
            pass

        async def run(self, task):
            pass

    import pipecat.pipeline.runner as runner_mod
    from app import pipeline

    monkeypatch.setattr(pipeline, "build_pipeline", fake_build)
    monkeypatch.setattr(runner_mod, "PipelineRunner", FakeRunner)
    return built


def test_ws_rejects_a_call_id_that_was_never_dialled(client, fake_runtime):
    c = client()
    assert ws_rejects(c, start_msg(call_id=OTHER)) == 1008
    assert fake_runtime == []


def test_ws_rejects_a_call_sid_that_does_not_match_the_dial(client, fake_runtime):
    c = client()
    main.state.phone_pending[CALL] = ("CA1", time.monotonic())
    assert ws_rejects(c, start_msg(call_sid="CA-forged")) == 1008
    assert fake_runtime == []


def test_ws_rejects_a_live_call(client, fake_runtime):
    c = client()
    main.state.phone_pending[CALL] = ("CA1", time.monotonic())
    main.state.live_calls[CALL] = "pc-1"
    assert ws_rejects(c, start_msg()) == 1008
    assert fake_runtime == []


def test_ws_rejects_a_malformed_start(client, fake_runtime):
    c = client()
    assert ws_rejects(c, {"event": "start", "start": {"customParameters": {"callId": "nope"}}}) == 1008


def test_ws_runs_the_pipeline_at_8khz_over_the_twilio_serializer(client, fake_runtime):
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport

    c = client()
    main.state.phone_pending[CALL] = ("CA1", time.monotonic())
    with c.websocket_connect("/ws/twilio") as ws:
        ws.send_json({"event": "connected"})
        ws.send_json(start_msg())
    ((call_id, transport, rate),) = fake_runtime
    assert call_id == CALL and rate == 8000
    assert isinstance(transport, FastAPIWebsocketTransport)
    ser = transport._params.serializer
    assert isinstance(ser, TwilioFrameSerializer)
    assert (ser._stream_sid, ser._call_sid, ser._account_sid, ser._auth_token) == ("MZ1", "CA1", SID, TOKEN)
    assert transport._params.allowed_origins == []
    assert main.state.live_calls == {} and main.state.phone_pending == {}


# ---- tunnel guard ---------------------------------------------------------------

TUNNEL_HEADERS = [
    {"Cf-Connecting-Ip": "203.0.113.9"},
    {"Cf-Ray": "8a1b2c3d4e5f-BOM"},
    {"X-Forwarded-For": "203.0.113.9"},
    {"Forwarded": "for=203.0.113.9;proto=https"},
]
LOCAL_ONLY = [
    ("post", "/v1/phone-call", {"callId": CALL, "numberId": "0"}),
    ("get", "/v1/phone/allowed", None),
    ("post", "/api/offer", {"sdp": "v=0", "type": "offer", "requestData": {"callId": CALL}}),
    ("patch", "/api/offer", {"pc_id": "pc-1", "candidates": []}),
    ("post", "/v1/text-call", {"callId": CALL}),
    ("post", "/v1/text-turn", {"callId": CALL, "text": "hi"}),
    ("get", "/v1/eval/latest", None),
    ("get", "/v1/llm/status", None),
]


@pytest.mark.parametrize("headers", TUNNEL_HEADERS)
@pytest.mark.parametrize("method,path,body", LOCAL_ONLY)
def test_tunnelled_requests_reach_only_the_twilio_stream(client, headers, method, path, body):
    hits = []
    c = client(twilio=lambda r: hits.append(r) or httpx.Response(201, json={"sid": "CA1"}))
    kwargs = {"headers": headers} | ({"json": body} if body is not None else {})
    r = getattr(c, method)(path, **kwargs)
    assert r.status_code == 403 and r.json() == {"detail": "LOCAL_ONLY"}
    assert hits == [] and main.state.phone_pending == {}


@pytest.mark.parametrize("headers", TUNNEL_HEADERS)
def test_tunnelled_health_is_allowed(client, headers):
    assert client().get("/health", headers=headers).status_code == 200


@pytest.mark.parametrize("headers", TUNNEL_HEADERS)
def test_twilio_can_fetch_twiml_through_the_tunnel_for_a_pending_call_only(client, headers):
    c = client()
    assert c.post(f"/twilio/twiml?callId={CALL}", headers=headers).status_code == 404
    main.state.phone_pending[CALL] = ("CA1", time.monotonic())
    r = c.post(f"/twilio/twiml?callId={CALL}", headers=headers)
    assert r.status_code == 200 and r.text == phone.twiml(BASE, CALL)


def test_a_tunnelled_websocket_to_another_path_is_refused(client):
    @main.app.websocket("/ws/test-only-echo")
    async def echo(ws: main.WebSocket):
        await ws.accept()
        await ws.send_text("reached")

    c = client()
    try:
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect("/ws/test-only-echo", headers=TUNNEL_HEADERS[0]) as ws:
                ws.receive_text()
        assert e.value.code == 1008
        with c.websocket_connect("/ws/test-only-echo") as ws:
            assert ws.receive_text() == "reached"
    finally:
        main.app.router.routes = [r for r in main.app.router.routes if getattr(r, "path", "") != "/ws/test-only-echo"]


@pytest.mark.parametrize("headers", TUNNEL_HEADERS)
def test_the_twilio_stream_still_works_through_the_tunnel(client, fake_runtime, headers):
    c = client()
    main.state.phone_pending[CALL] = ("CA1", time.monotonic())
    with c.websocket_connect("/ws/twilio", headers=headers) as ws:
        ws.send_json({"event": "connected"})
        ws.send_json(start_msg())
    assert [b[0] for b in fake_runtime] == [CALL]
