"""A reviewer's transcript correction during a live call reaches the agent's session: a corrected mobile number or date of
birth replaces what was misheard, the model is told, and the next verification uses it without spending an attempt."""
import asyncio

from fastapi.testclient import TestClient

from app import main
from app.support_brain import CORRECTION_NOTE, SupportBrain
from app.vocab import Route, ToolError
from tests.test_brain import Scripted, text, tool_call
from tests.test_verify_capture import CALL, RAHUL, make, verify_result

OTHER_CALL = "77777777-7777-7777-7777-777777777777"
MISHEARD = "my number is 98765 00003 and I was born on 3rd November 1985"
CORRECTED = "my number is 98765 00002 and I was born on 3rd November 1985"
MODEL_COPY = {"mobile": "9876500003", "date_of_birth": "1985-11-03"}  # the model keeps repeating the misheard digits
CALLER_SEQ = 1  # the misheard caller turn is the first turn recorded by `make` (no greeting is opened)


def path(call_id: str = CALL, seq: int = CALLER_SEQ) -> str:
    return Route.SUPPORT_TURN_CORRECTION.format(call_id=call_id, seq=seq)


def live(brain: SupportBrain) -> TestClient:
    main.state.support.clear()
    main.state.support[CALL] = brain
    return TestClient(main.app)


def test_correction_replaces_a_misheard_mobile_and_the_next_verify_uses_it():
    llm = Scripted(tool_call("verify_customer", MODEL_COPY), text("Those details don't match. Could you confirm both?"),
                   tool_call("verify_customer", MODEL_COPY, "c2"), text("Thanks Rahul, you are verified."))
    brain, sim = make(llm)
    first = verify_result(asyncio.run(brain.reply(MISHEARD)))
    assert first["error"] == ToolError.VERIFICATION_FAILED and brain.call.verify_failures == 1
    assert sim.verify_bodies()[0]["mobile"] == "9876500003"

    try:
        r = live(brain).post(path(), json={"text": CORRECTED})
    finally:
        main.state.support.clear()
    assert r.status_code == 200 and r.json() == {"applied": True, "heard": {"mobile": True, "dob": True}}
    assert RAHUL["mobile"] not in r.text and RAHUL["dob"] not in r.text  # booleans only: digits are never echoed back
    assert brain.call.heard_mobile == RAHUL["mobile"] and brain.call.heard_dob == RAHUL["dob"] and brain.call.heard_digits is None
    assert brain.call.verify_failures == 1 and len(sim.verify_bodies()) == 1  # the correction itself spends no attempt

    second = verify_result(asyncio.run(brain.reply("yes please verify")))
    assert second["verified"] is True and brain.call.verified
    assert sim.verify_bodies()[-1] == {"mobile": RAHUL["mobile"], "dob": RAHUL["dob"], "call_id": CALL}
    assert brain.call.verify_failures == 1


def test_correction_after_the_second_mismatch_refills_the_forgotten_field():
    """After the second failure the wrong field is forgotten and only a fresh caller turn may refill it; the reviewer's
    correction counts as that turn, so the next verify uses the corrected number instead of asking again."""
    llm = Scripted(tool_call("verify_customer", MODEL_COPY), text("Please confirm both."),
                   tool_call("verify_customer", MODEL_COPY, "c2"), text("That number is not registered."),
                   tool_call("verify_customer", MODEL_COPY, "c3"), text("Verified."))
    brain, sim = make(llm)
    asyncio.run(brain.reply(MISHEARD))
    asyncio.run(brain.reply("Yes, 98765 00003 and 3 November 1985"))
    assert brain.call.heard_mobile is None and brain.call.verify_failures == 2

    heard = asyncio.run(brain.apply_correction(CALLER_SEQ, CORRECTED))
    assert heard == {"mobile": True, "dob": True} and brain.call.heard_mobile == RAHUL["mobile"]
    third = verify_result(asyncio.run(brain.reply("please try again")))
    assert third["verified"] is True and sim.verify_bodies()[-1]["mobile"] == RAHUL["mobile"]
    assert brain.call.verify_failures == 2


def test_correction_reaches_the_model_history():
    brain, sim = make(Scripted())
    heard = asyncio.run(brain.apply_correction(CALLER_SEQ, "No, I meant my vehicle loan"))
    assert heard == {"mobile": False, "dob": False}
    last = brain._messages[-1]
    assert last["role"] == "user" and last["content"] == CORRECTION_NOTE.format(text="No, I meant my vehicle loan")
    assert "No, I meant my vehicle loan" in last["content"] and "Use this instead of what was heard" in last["content"]
    assert sim.requests == [] and brain.call.heard_mobile is None and brain.call.heard_dob is None  # no bank call, nothing heard


def test_correction_for_an_ended_or_unknown_call_is_404():
    brain, _ = make(Scripted())
    try:
        c = live(brain)
        assert c.post(path(OTHER_CALL), json={"text": CORRECTED}).status_code == 404  # unknown
        main.state.support.pop(CALL)  # ended: the brain is gone from the live calls
        r = c.post(path(), json={"text": CORRECTED})
        assert r.status_code == 404 and r.json() == {"detail": "no live call"}
        assert c.post(path("not-a-uuid"), json={"text": CORRECTED}).status_code == 422
    finally:
        main.state.support.clear()
    assert brain._messages[-1]["role"] == "assistant"  # nothing reached the brain


def test_blank_correction_is_rejected():
    brain, _ = make(Scripted())
    try:
        c = live(brain)
        assert c.post(path(), json={"text": "   "}).status_code == 400
        assert c.post(path(), json={"text": "x" * 2001}).status_code == 400
        assert c.post(path(), json={}).status_code == 422
    finally:
        main.state.support.clear()
    assert brain._messages[-1]["role"] == "assistant" and brain.call.heard_mobile is None


def test_route_is_local_only():
    brain, _ = make(Scripted())
    try:
        r = live(brain).post(path(), json={"text": CORRECTED}, headers={"x-forwarded-for": "203.0.113.9"})
    finally:
        main.state.support.clear()
    assert r.status_code == 403 and r.json() == {"detail": "LOCAL_ONLY"}
    assert brain.call.heard_mobile is None and brain._messages[-1]["role"] == "assistant"
