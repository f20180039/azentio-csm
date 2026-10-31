"""Verification uses what the caller said, not what the model copied: good values are kept, only the missing one is asked for,
and a bank mismatch names the wrong field only after the second failed attempt."""
import asyncio
import json
from datetime import date

import httpx

from app.api_client import SupportCallsApi
from app.config import Settings
from app.simulator_client import SimulatorClient
from app.support_brain import SupportBrain
from app.support_tools import CallSession
from app.vocab import ToolError, VerifyField
from tests.test_brain import Scripted, text, tool_call

CALL = "44444444-4444-4444-4444-444444444444"
TODAY = date(2026, 10, 31)
RAHUL = {"mobile": "9876500002", "dob": "1985-11-03"}


class MismatchSimulator:
    """The bank's verify endpoint, saying internally which field failed (the agent decides when to pass that on)."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.failures = 0

    def verify_bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith("/verify")]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not request.url.path.endswith("/verify"):
            return httpx.Response(404, json={"error": "NOT_FOUND"})
        body = json.loads(request.content)
        if self.failures >= 3:
            return httpx.Response(423, json={"error": "LOCKED"})
        if body["mobile"] == RAHUL["mobile"] and body["dob"] == RAHUL["dob"]:
            return httpx.Response(200, json={"session": "tok", "expires_in": 900, "customer": {"customer_ref": "CUST-1002", "first_name": "Rahul"}})
        self.failures += 1
        mismatch = "DOB_MISMATCH" if body["mobile"] == RAHUL["mobile"] else "MOBILE_NOT_FOUND"
        return httpx.Response(401, json={"error": "VERIFICATION_FAILED", "attempts_left": 3 - self.failures, "mismatch": mismatch})


def make(llm):
    sim = MismatchSimulator()
    spring = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    call = CallSession(CALL, today=TODAY)
    brain = SupportBrain(llm, SimulatorClient(Settings(), transport=httpx.MockTransport(sim)), SupportCallsApi(Settings(), transport=spring), call)
    return brain, sim


def verify_result(turn) -> dict:
    return next(t.result for t in turn.tool_calls if t.name == "verify_customer")


def test_dropped_digit_from_the_model_is_replaced_by_what_the_caller_said():
    llm = Scripted(tool_call("verify_customer", {"mobile": "987650002", "date_of_birth": "1985-11-03"}), text("Thanks Rahul, you are verified."))
    brain, sim = make(llm)
    turn = asyncio.run(brain.reply("My number is 98765 00002 and my date of birth is 3rd November 1985"))
    assert sim.verify_bodies() == [{"mobile": "9876500002", "dob": "1985-11-03", "call_id": CALL}]
    assert verify_result(turn)["verified"] is True and brain.call.verified
    assert brain.call.heard_mobile == "9876500002" and brain.call.heard_dob == "1985-11-03"


def test_invented_details_are_never_sent():
    llm = Scripted(tool_call("verify_customer", {"mobile": "5551234567", "date_of_birth": "1990-04-12"}), text("Could I have your registered mobile number and date of birth?"))
    brain, sim = make(llm)
    turn = asyncio.run(brain.reply("I want to know my loan EMI"))
    out = verify_result(turn)
    assert out["error"] == ToolError.MISSING_DETAILS
    assert out["missing"] == [VerifyField.MOBILE, VerifyField.DOB] and out["have"] == []
    assert out["note"] == "Ask for the registered mobile number and date of birth."
    assert sim.verify_bodies() == [] and brain.call.verify_failures == 0 and not brain.call.model_may_fill


def test_a_loan_reference_does_not_unlock_invented_details():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9123456789", "date_of_birth": "1990-04-12"}),
                   text("Could I have your registered mobile number and date of birth?"))
    brain, sim = make(llm)
    out = verify_result(asyncio.run(brain.reply("what is the status of my loan PL-31002")))
    assert out["error"] == ToolError.MISSING_DETAILS and out["missing"] == [VerifyField.MOBILE, VerifyField.DOB]
    assert sim.verify_bodies() == [] and brain.call.verify_failures == 0 and not brain.call.model_may_fill


def test_an_amount_does_not_unlock_an_invented_date():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1990-04-12"}), text("And your date of birth?"))
    brain, sim = make(llm)
    out = verify_result(asyncio.run(brain.reply("My number is 98765 00002, I will pay 5 to 6 lakh")))
    assert out["error"] == ToolError.MISSING_DETAILS and out["missing"] == [VerifyField.DOB]
    assert sim.verify_bodies() == [] and not brain.call.model_may_fill


def test_the_callers_own_digits_do_not_unlock_an_invented_date():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1990-04-12"}), text("And your date of birth?"))
    brain, sim = make(llm)
    out = verify_result(asyncio.run(brain.reply("My number is 98765 00002")))
    assert out["error"] == ToolError.MISSING_DETAILS and out["missing"] == [VerifyField.DOB] and out["have"] == [VerifyField.MOBILE]
    assert out["note"] == "Ask only for the date of birth; the mobile number is already noted."
    assert sim.verify_bodies() == [] and brain.call.verify_failures == 0 and not brain.call.model_may_fill


def test_only_the_missing_field_is_asked_for():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9876500002"}), text("And your date of birth?"),
                   tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1985-11-03"}, "c2"), text("Verified, thank you."))
    brain, sim = make(llm)
    first = verify_result(asyncio.run(brain.reply("My number is 98765 00002")))
    assert first["error"] == ToolError.MISSING_DETAILS
    assert first["missing"] == [VerifyField.DOB] and first["have"] == [VerifyField.MOBILE]
    assert first["note"] == "Ask only for the date of birth; the mobile number is already noted."
    assert sim.verify_bodies() == [] and brain.call.verify_failures == 0

    second = verify_result(asyncio.run(brain.reply("3rd November 1985")))
    assert second["verified"] is True
    assert sim.verify_bodies() == [{"mobile": "9876500002", "dob": "1985-11-03", "call_id": CALL}]


def test_a_short_mobile_is_asked_for_again_alone():
    llm = Scripted(tool_call("verify_customer", {"mobile": "987650002", "date_of_birth": "1985-11-03"}), text("Could you repeat the mobile number?"))
    brain, sim = make(llm)
    out = verify_result(asyncio.run(brain.reply("98765 0002, born 3 November 1985")))
    assert out["error"] == ToolError.MISSING_DETAILS
    assert out["missing"] == [VerifyField.MOBILE] and out["have"] == [VerifyField.DOB]
    assert out["note"] == "Ask only for the registered 10-digit mobile number; the date of birth is already noted. The number heard had 9 digits."
    assert sim.verify_bodies() == [] and brain.call.verify_failures == 0
    assert brain.call.heard_dob == "1985-11-03" and brain.call.heard_mobile is None


def test_repeated_zeros_said_with_a_pause_are_verified():
    llm = Scripted(tool_call("verify_customer", {"mobile": "98765", "date_of_birth": "1985-11-03"}), text("Thanks Rahul, you are verified."))
    brain, sim = make(llm)
    turn = asyncio.run(brain.reply("my number is nine eight seven six five, zero zero zero zero two, born 3rd November 1985"))
    assert sim.verify_bodies() == [{"mobile": "9876500002", "dob": "1985-11-03", "call_id": CALL}]
    assert verify_result(turn)["verified"] is True and brain.call.heard_mobile == "9876500002"


def test_an_over_long_mobile_is_asked_for_again_not_cut():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9876500000", "date_of_birth": "1985-11-03"}), text("Could you repeat the mobile number?"))
    brain, sim = make(llm)
    out = verify_result(asyncio.run(brain.reply("98765 double zero triple zero two, born 3rd November 1985")))
    assert out["error"] == ToolError.MISSING_DETAILS
    assert out["missing"] == [VerifyField.MOBILE] and out["have"] == [VerifyField.DOB]
    assert out["note"].endswith("The number heard had 11 digits.")
    assert sim.verify_bodies() == [] and brain.call.heard_mobile is None and brain.call.heard_dob == "1985-11-03"


def test_a_collapsed_repeat_is_asked_for_again_with_its_count():
    # Whisper wrote "zero zero zero zero" as "zero zero": the code cannot recover the digits, so the mobile is re-asked alone
    llm = Scripted(tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1985-11-03"}), text("Could you repeat the mobile number?"))
    brain, sim = make(llm)
    out = verify_result(asyncio.run(brain.reply("nine eight seven six five zero zero two, born 3rd November 1985")))
    assert out["error"] == ToolError.MISSING_DETAILS and out["missing"] == [VerifyField.MOBILE] and out["have"] == [VerifyField.DOB]
    assert out["note"].endswith("The number heard had 8 digits.")
    assert sim.verify_bodies() == [] and brain.call.heard_mobile is None


def test_first_mismatch_does_not_say_which_field():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1990-01-01"}), text("Those details don't match. Could you confirm both?"))
    brain, sim = make(llm)
    out = verify_result(asyncio.run(brain.reply("98765 00002, 1 January 1990")))
    assert out["error"] == ToolError.VERIFICATION_FAILED and out["attempts_left"] == 2
    assert out["note"] == ("The details do not match our records. Ask the caller to confirm both their mobile number and date of birth. "
                           "Do not say which one is wrong.")
    assert "date of birth does not match" not in out["note"] and "not registered" not in out["note"]
    assert "mismatch" not in out  # the bank's reason stays out of the model's sight until the second failure
    assert brain.call.verify_failures == 1 and brain.call.heard_mobile == "9876500002" and brain.call.heard_dob == "1990-01-01"


def test_second_mismatch_names_the_wrong_field_and_keeps_the_other():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1990-01-01"}), text("Please confirm both."),
                   tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1990-01-01"}, "c2"), text("The date of birth does not match; once more?"),
                   tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1985-11-03"}, "c3"), text("Verified."))
    brain, sim = make(llm)
    asyncio.run(brain.reply("98765 00002, 1 January 1990"))
    second = verify_result(asyncio.run(brain.reply("Yes, 98765 00002 and 1 January 1990")))
    assert second["error"] == ToolError.VERIFICATION_FAILED and second["attempts_left"] == 1
    assert second["note"] == ("The date of birth does not match the mobile number. Ask only for the date of birth; keep the mobile number. "
                              "This is the last attempt.")
    assert brain.call.heard_dob is None and brain.call.heard_mobile == "9876500002" and brain.call.verify_failures == 2

    third = verify_result(asyncio.run(brain.reply("Sorry, 3rd November 1985")))
    assert third["verified"] is True and brain.call.verified
    assert [b["dob"] for b in sim.verify_bodies()] == ["1990-01-01", "1990-01-01", "1985-11-03"]
    assert all(b["mobile"] == "9876500002" for b in sim.verify_bodies())


def test_a_retry_in_the_same_turn_after_the_second_mismatch_spends_no_attempt():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1990-01-01"}), text("Please confirm both."),
                   tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1990-01-01"}, "c2"),
                   tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1990-01-01"}, "c3"),  # the model's stale copy
                   text("Could you tell me your date of birth once more?"))
    brain, sim = make(llm)
    asyncio.run(brain.reply("98765 00002, 1 January 1990"))
    turn = asyncio.run(brain.reply("Yes, 98765 00002 and 1 January 1990"))
    retry = [t.result for t in turn.tool_calls if t.name == "verify_customer"][-1]
    assert retry["error"] == ToolError.MISSING_DETAILS and retry["missing"] == [VerifyField.DOB] and retry["have"] == [VerifyField.MOBILE]
    assert brain.call.verify_failures == 2 and not brain.call.locked and len(sim.verify_bodies()) == 2


def test_second_mismatch_on_an_unknown_mobile_asks_for_the_mobile_alone():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9380939280", "date_of_birth": "1985-11-03"}), text("Please confirm both."),
                   tool_call("verify_customer", {"mobile": "9380939280", "date_of_birth": "1985-11-03"}, "c2"), text("That number is not registered."))
    brain, sim = make(llm)
    asyncio.run(brain.reply("93809 39280, 3 November 1985"))
    second = verify_result(asyncio.run(brain.reply("Yes, 93809 39280 and 3 November 1985")))
    assert second["note"] == ("That mobile number is not registered with us. Ask only for the registered mobile number; keep the date of birth. "
                              "This is the last attempt.")
    assert brain.call.heard_mobile is None and brain.call.heard_dob == "1985-11-03" and brain.call.heard_digits is None


def test_kannada_number_words_fall_back_to_the_models_digits():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "1985-11-03"}), text("ಧನ್ಯವಾದಗಳು, ಪರಿಶೀಲಿಸಲಾಗಿದೆ."))
    brain, sim = make(llm)
    turn = asyncio.run(brain.reply("ನನ್ನ ಸಂಖ್ಯೆ ಒಂಬತ್ತು ಎಂಟು ಏಳು ಆರು ಐದು ಸೊನ್ನೆ ಸೊನ್ನೆ ಸೊನ್ನೆ ಸೊನ್ನೆ ಎರಡು, ಹುಟ್ಟಿದ ದಿನಾಂಕ ಮೂರು ನವೆಂಬರ್ ಸಾವಿರದ ಒಂಬೈನೂರ ಎಂಬತ್ತೈದು"))
    assert brain.call.model_may_fill == {VerifyField.MOBILE, VerifyField.DOB} and brain.call.heard_mobile is None and brain.call.heard_dob is None
    assert verify_result(turn)["verified"] is True
    assert sim.verify_bodies() == [{"mobile": "9876500002", "dob": "1985-11-03", "call_id": CALL}]


def test_a_model_dob_outside_a_lifetime_is_not_sent():
    llm = Scripted(tool_call("verify_customer", {"mobile": "9876500002", "date_of_birth": "2026-11-05"}), text("Your date of birth, please?"))
    brain, sim = make(llm)
    out = verify_result(asyncio.run(brain.reply("98765 00002")))
    assert out["error"] == ToolError.MISSING_DETAILS and out["missing"] == [VerifyField.DOB]
    assert sim.verify_bodies() == []
