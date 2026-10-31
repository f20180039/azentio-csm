"""The support desk by phone: Twilio's inbound webhook, the support media stream, "call me" and the transfer on escalation."""
import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main, phone, support_pipeline
from app.api_client import SupportCallsApi
from app.config import Settings
from app.simulator_client import SimulatorClient
from app.support_brain import SupportTurn, ToolTrace
from app.support_tools import CallSession
from app.vocab import HandoffMode, Route, SupportTool
from tests.test_brain import Scripted
from tests.test_phone import ALLOWED, BASE, CONFIGURED, SID, TOKEN, TUNNEL_HEADERS
from tests.test_support_tools import FakeSimulator

CALL = "55555555-5555-5555-5555-555555555555"
INCOMING_URL = BASE + Route.TWILIO_SUPPORT_INCOMING
FORM = {"CallSid": "CA9", "From": "+15005550199", "To": "+15005550006", "AccountSid": SID, "CallStatus": "ringing"}


@pytest.fixture
def desk():
    spring: list[tuple] = []
    dials: list[httpx.Request] = []

    def records(r: httpx.Request) -> httpx.Response:
        spring.append((r.method, r.url.path, json.loads(r.content) if r.content else None))
        if r.method == "POST" and r.url.path.endswith("/support/calls"):
            return httpx.Response(201, json={"id": CALL})
        return httpx.Response(200, json={})

    def make(settings: Settings = CONFIGURED, twilio=None) -> TestClient:
        main.state._settings = settings
        main.state.llm = Scripted()
        main.state.sim = SimulatorClient(Settings(), transport=httpx.MockTransport(FakeSimulator()))
        main.state.support_calls = SupportCallsApi(Settings(), transport=httpx.MockTransport(records))
        main.state.classifier = lambda: None
        main.state.twilio_transport = httpx.MockTransport(twilio or (lambda r: dials.append(r) or httpx.Response(201, json={"sid": "CA1"})))
        main.state.tunnel_transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ok"}))
        return TestClient(main.app)

    make.spring, make.dials = spring, dials
    yield make
    main.state._settings = None
    main.state.llm = main.state.sim = main.state.support_calls = None
    main.state.twilio_transport = main.state.tunnel_transport = None
    main.state.support.clear()
    main.state.live_calls.clear()
    main.state.phone_pending.clear()
    del main.state.classifier


def signed(params: dict, url: str = INCOMING_URL, token: str = TOKEN) -> dict:
    return {"X-Twilio-Signature": phone.signature(token, url, params)}


# ---- signature ------------------------------------------------------------------


def test_signature_matches_twilios_documented_example():
    # the worked example used by Twilio's own request validator (twilio-python's test suite)
    params = {"CallSid": "CA1234567890ABCDE", "Caller": "+14158675309", "Digits": "1234", "From": "+14158675309", "To": "+18005551212"}
    assert phone.signature("12345", "https://mycompany.com/myapp.php?foo=1&bar=2", params) == "RSOYDt4T1cUTdK1PDd93/VVr8B8="


def test_signature_check_refuses_a_missing_header_or_token():
    assert not phone.signature_valid(TOKEN, INCOMING_URL, FORM, None)
    assert not phone.signature_valid("", INCOMING_URL, FORM, phone.signature("", INCOMING_URL, FORM))


# ---- POST /twilio/support/incoming ----------------------------------------------


def test_a_signed_incoming_call_starts_a_phone_support_call_and_streams_it(desk):
    c = desk()
    r = c.post(Route.TWILIO_SUPPORT_INCOMING, data=FORM, headers=signed(FORM))
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert r.text == phone.twiml(BASE, CALL, Route.TWILIO_SUPPORT_WS)
    assert '<Stream url="wss://demo-tunnel.trycloudflare.com/ws/twilio/support">' in r.text
    assert ("POST", "/api/v1/support/calls", {"channel": "PHONE"}) in desk.spring
    assert main.state.support[CALL].call.caller_ref == "+15005550199"
    assert main.state.phone_pending[CALL][0] == "CA9"


def test_a_bad_signature_is_403_and_starts_nothing(desk):
    c = desk()
    r = c.post(Route.TWILIO_SUPPORT_INCOMING, data=FORM, headers=signed({**FORM, "From": "+15005550100"}))
    assert r.status_code == 403
    assert c.post(Route.TWILIO_SUPPORT_INCOMING, data=FORM).status_code == 403
    assert c.post(Route.TWILIO_SUPPORT_INCOMING, data=FORM, headers=signed(FORM, token="wrong")).status_code == 403
    assert desk.spring == [] and main.state.support == {}


def test_incoming_is_403_when_twilio_is_not_configured(desk):
    c = desk(Settings())
    assert c.post(Route.TWILIO_SUPPORT_INCOMING, data=FORM, headers=signed(FORM, token="")).status_code == 403
    assert desk.spring == []


@pytest.mark.parametrize("headers", TUNNEL_HEADERS)
def test_twilio_reaches_the_incoming_webhook_through_the_tunnel(desk, headers):
    r = desk().post(Route.TWILIO_SUPPORT_INCOMING, data=FORM, headers=signed(FORM) | headers)
    assert r.status_code == 200


@pytest.mark.parametrize("headers", TUNNEL_HEADERS)
def test_call_me_is_local_only(desk, headers):
    c = desk()
    r = c.post(Route.SUPPORT_PHONE_CALL, json={"numberId": "0"}, headers=headers)
    assert r.status_code == 403 and r.json() == {"detail": "LOCAL_ONLY"}
    assert desk.dials == []


# ---- WS /ws/twilio/support -------------------------------------------------------


@pytest.fixture
def fake_support_runtime(monkeypatch):
    built = []

    def fake_build(settings, brain, transport, audio_sample_rate=None):
        built.append((brain, transport, audio_sample_rate))
        assert main.state.live_calls.get(brain.call.call_id) == f"twilio:{brain.call.phone_call_sid}"
        return object()

    class FakeRunner:
        def __init__(self, **_):
            pass

        async def run(self, task):
            pass

    import pipecat.pipeline.runner as runner_mod

    monkeypatch.setattr(support_pipeline, "build_support_pipeline", fake_build)
    monkeypatch.setattr(runner_mod, "PipelineRunner", FakeRunner)
    return built


def start_msg(call_id=CALL, call_sid="CA9"):
    return {"event": "start", "streamSid": "MZ9",
            "start": {"streamSid": "MZ9", "callSid": call_sid, "accountSid": SID, "customParameters": {"callId": call_id}}}


def test_the_support_stream_runs_the_support_pipeline_at_8khz_with_the_call_sid(desk, fake_support_runtime):
    from pipecat.serializers.twilio import TwilioFrameSerializer
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport

    c = desk(Settings(**{**CONFIGURED.__dict__, "human_agent_number": "+919800000000"}))
    c.post(Route.TWILIO_SUPPORT_INCOMING, data=FORM, headers=signed(FORM))
    with c.websocket_connect(Route.TWILIO_SUPPORT_WS) as ws:
        ws.send_json({"event": "connected"})
        ws.send_json(start_msg())
    ((brain, transport, rate),) = fake_support_runtime
    assert brain.call.call_id == CALL and rate == 8000
    assert brain.call.phone_call_sid == "CA9" and brain.call.transfer_to == "+919800000000"
    assert brain.call.caller_ref == "+15005550199"
    assert isinstance(transport, FastAPIWebsocketTransport)
    ser = transport._params.serializer
    assert isinstance(ser, TwilioFrameSerializer) and (ser._stream_sid, ser._call_sid) == ("MZ9", "CA9")
    assert main.state.live_calls == {} and main.state.phone_pending == {} and main.state.support == {}


def test_the_support_stream_sets_no_transfer_number_when_none_is_configured(desk, fake_support_runtime):
    c = desk()
    c.post(Route.TWILIO_SUPPORT_INCOMING, data=FORM, headers=signed(FORM))
    with c.websocket_connect(Route.TWILIO_SUPPORT_WS) as ws:
        ws.send_json(start_msg())
    assert fake_support_runtime[0][0].call.transfer_to is None


@pytest.mark.parametrize("msg", [start_msg(call_sid="CA-forged"), start_msg(call_id="66666666-6666-6666-6666-666666666666")])
def test_the_support_stream_refuses_calls_it_did_not_answer(desk, fake_support_runtime, msg):
    c = desk()
    c.post(Route.TWILIO_SUPPORT_INCOMING, data=FORM, headers=signed(FORM))
    with c.websocket_connect(Route.TWILIO_SUPPORT_WS) as ws:
        ws.send_json(msg)
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_text()
    assert e.value.code == 1008 and fake_support_runtime == []


def test_the_renewal_stream_refuses_a_support_call(desk, fake_support_runtime):
    c = desk()
    c.post(Route.TWILIO_SUPPORT_INCOMING, data=FORM, headers=signed(FORM))
    assert c.post(f"{Route.TWILIO_TWIML}?callId={CALL}").status_code == 404
    with c.websocket_connect(Route.TWILIO_WS) as ws:
        ws.send_json(start_msg())
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()


# ---- POST /support/phone-call -----------------------------------------------------


@pytest.mark.parametrize("body", [{"to": "+919999999999"}, {"numberId": "7"}, {}])
def test_call_me_refuses_numbers_off_the_allow_list(desk, body):
    c = desk()
    assert c.post(Route.SUPPORT_PHONE_CALL, json=body).status_code == 403
    assert desk.dials == [] and desk.spring == []


def test_call_me_without_twilio_is_503(desk):
    assert desk(Settings()).post(Route.SUPPORT_PHONE_CALL, json={"to": ALLOWED[0]}).status_code == 503


@pytest.mark.parametrize("body", [{"to": ALLOWED[1]}, {"numberId": "1"}])
def test_call_me_dials_an_allowed_number_with_the_support_twiml(desk, body):
    c = desk()
    r = c.post(Route.SUPPORT_PHONE_CALL, json=body)
    assert r.status_code == 200 and r.json() == {"call_id": CALL, "status": "dialling"}
    (req,) = desk.dials
    form = parse_qs(req.content.decode())
    assert form["To"] == [ALLOWED[1]]
    assert form["Url"] == [f"{BASE}{Route.TWILIO_SUPPORT_TWIML}?callId={CALL}"]
    assert ("POST", "/api/v1/support/calls", {"channel": "PHONE"}) in desk.spring
    assert main.state.phone_pending[CALL][0] == "CA1" and main.state.support[CALL].call.caller_ref == ALLOWED[1]
    twiml = c.post(f"{Route.TWILIO_SUPPORT_TWIML}?callId={CALL}")
    assert twiml.status_code == 200 and twiml.text == phone.twiml(BASE, CALL, Route.TWILIO_SUPPORT_WS)
    assert c.post(Route.SUPPORT_PHONE_CALL, json=body).json()["detail"] == "PHONE_BUSY"


def test_call_me_twilio_failure_is_502_and_closes_the_call(desk):
    c = desk(twilio=lambda r: httpx.Response(400, json={"code": 21219, "message": f"{ALLOWED[0]} is unverified"}))
    r = c.post(Route.SUPPORT_PHONE_CALL, json={"numberId": "0"})
    assert r.status_code == 502 and ALLOWED[0] not in r.text
    assert main.state.phone_pending == {} and main.state.support == {}
    assert desk.spring[-1][1].endswith(f"/support/calls/{CALL}/end")


def test_support_twiml_is_404_for_an_unknown_call(desk):
    assert desk().post(f"{Route.TWILIO_SUPPORT_TWIML}?callId={CALL}").status_code == 404


# ---- transfer on escalation ---------------------------------------------------------


def escalation(mode: HandoffMode) -> SupportTurn:
    return SupportTurn("Connecting you to a colleague now.",
                       tool_calls=[ToolTrace(SupportTool.ESCALATE_TO_HUMAN, {}, {"ref": "ESC-1", "handoff": {"mode": mode}})])


def test_only_a_transfer_handoff_wants_a_transfer():
    assert support_pipeline.wants_transfer(escalation(HandoffMode.TRANSFER))
    assert not support_pipeline.wants_transfer(escalation(HandoffMode.CALLBACK))
    assert not support_pipeline.wants_transfer(SupportTurn("hi"))


def test_transfer_after_reply_dials_the_live_call_through_to_the_person():
    seen = []
    call = CallSession(CALL, phone_call_sid="CA9", transfer_to="+919800000000")
    transport = httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json={}))
    asyncio.run(support_pipeline.transfer_after_reply(CONFIGURED, call, delay=0, transport=transport))
    (req,) = seen
    assert req.url.path.endswith("/Calls/CA9.json")
    assert "<Dial>+919800000000</Dial>" in parse_qs(req.content.decode())["Twiml"][0]


class FakeBrain:
    def __init__(self, turn: SupportTurn, call: CallSession):
        self.turn, self.call = turn, call

    async def reply(self, text):
        return self.turn

    def mark_unheard(self):
        pass


@pytest.mark.parametrize("mode,transfers", [(HandoffMode.TRANSFER, 1), (HandoffMode.CALLBACK, 0)])
def test_a_phone_escalation_schedules_the_transfer(monkeypatch, mode, transfers):
    scheduled = []

    async def fake_transfer(settings, call, **_):
        scheduled.append((settings, call.phone_call_sid))
    monkeypatch.setattr(support_pipeline, "transfer_after_reply", fake_transfer)
    call = CallSession(CALL, phone_call_sid="CA9", transfer_to="+919800000000")

    async def scenario():
        responder = support_pipeline.SupportResponder(FakeBrain(escalation(mode), call), CONFIGURED)
        pushed = []

        async def push(frame, *_):
            pushed.append(frame)
        responder.push_frame = push
        await responder._answer("I want a person", responder._gate.generation)
        await asyncio.sleep(0)
        return pushed
    pushed = asyncio.run(scenario())
    assert pushed[0].text == "Connecting you to a colleague now."
    assert scheduled == [(CONFIGURED, "CA9")] * transfers


def test_the_greeting_is_queued_when_the_phone_stream_connects():
    """FastAPIWebsocketInputTransport fires on_client_connected from start(), after the socket is accepted, so a phone
    caller hears the greeting as soon as the pipeline starts, as the browser microphone does."""
    from app.support_prompt import GREETING
    from tests.test_pipeline import FakeTransport

    transport = FakeTransport()
    task = support_pipeline.build_support_pipeline(Settings(**{**CONFIGURED.__dict__, "groq_api_key": "test-key"}), FakeBrain(SupportTurn(""), CallSession(CALL)), transport,
                                                   audio_sample_rate=8000)
    queued = []

    async def record(frames):
        queued.extend(frames)
    task.queue_frames = record
    asyncio.run(transport._call_event_handler("on_client_connected", None))
    assert [f.text for f in queued] == [GREETING]

