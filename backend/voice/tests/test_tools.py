import asyncio
import json

import httpx
import pytest

from app.api_client import ApiUnavailable, InvalidCallId, RenewalsApi
from app.config import Settings
from app.tools import TOOL_SCHEMAS, run_tool

CALL = "11111111-1111-1111-1111-111111111111"


def api_with(handler) -> RenewalsApi:
    return RenewalsApi(Settings(), transport=httpx.MockTransport(handler))


def run(api, name, args):
    return asyncio.run(run_tool(api, CALL, name, args))


def problem(status: int, detail: str) -> httpx.Response:
    return httpx.Response(status, json={"type": "about:blank", "title": "x", "status": status, "detail": detail})


def test_refusal_is_returned_not_raised():
    out = run(api_with(lambda r: problem(403, "IDENTITY_NOT_VERIFIED")), "get_policy", {})
    assert out == {"error": "IDENTITY_NOT_VERIFIED", "status": 403, "mustHandoff": False}


def test_must_handoff_codes():
    out = run(api_with(lambda r: problem(409, "VERIFY_LOCKED")), "verify_identity", {"date_of_birth": "1980-01-01"})
    assert out["mustHandoff"] is True
    out = run(api_with(lambda r: problem(403, "MUST_HANDOFF")), "list_allowed_options", {})
    assert out["mustHandoff"] is True


def test_quote_maps_arguments():
    seen = {}

    def handler(r: httpx.Request) -> httpx.Response:
        seen["path"] = r.url.path
        seen["json"] = json.loads(r.content)
        seen["auth"] = r.headers["authorization"]
        return httpx.Response(200, json={"quoteId": "q", "mustHandoff": False})

    out = run(
        api_with(handler), "quote_renewal",
        {"drop_addons": ["OPD"], "payment_plan": "quarterly", "discount_percent": 0},
    )
    assert seen["json"] == {"dropAddons": ["OPD"], "paymentPlan": "quarterly", "discountPercent": 0}
    assert seen["path"] == f"/api/v1/renewals/calls/{CALL}/quote"
    assert seen["auth"].startswith("Basic ")
    assert out["quoteId"] == "q"


def test_verify_handoff_payment_link_and_end_shapes():
    seen = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append((r.method, r.url.path.rsplit("/", 1)[1], json.loads(r.content) if r.content else None))
        return httpx.Response(200, json={"ok": True})

    api = api_with(handler)
    run(api, "verify_identity", {"date_of_birth": "1980-01-01"})
    run(api, "send_payment_link", {"quote_id": "q1"})
    run(api, "handoff_to_human", {"reason": "death", "callback_time": "2026-11-01T10:00:00Z"})
    run(api, "end_call", {})
    assert seen == [
        ("POST", "verify", {"dateOfBirth": "1980-01-01"}),
        ("POST", "payment-link", {"quoteId": "q1"}),
        ("POST", "handoff", {"reason": "death", "callbackAt": "2026-11-01T10:00:00Z"}),
        ("POST", "end", None),
    ]


def test_turn_accepts_empty_204():
    api = api_with(lambda r: httpx.Response(204))
    assert asyncio.run(api.turn(CALL, "user", "hello")) == {}


def test_unknown_tool():
    assert run(api_with(lambda r: httpx.Response(200, json={})), "nope", {}) == {"error": "UNKNOWN_TOOL"}


def test_server_error_raises():
    with pytest.raises(ApiUnavailable):
        run(api_with(lambda r: httpx.Response(500, text="boom")), "get_policy", {})


def test_network_error_raises():
    def handler(r):
        raise httpx.ConnectError("down")

    with pytest.raises(ApiUnavailable):
        asyncio.run(api_with(handler).policy(CALL))


def test_schemas_cover_all_tools():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert names == {"verify_identity", "get_policy", "list_allowed_options", "quote_renewal",
                     "send_payment_link", "handoff_to_human", "end_call"}


def test_malformed_arguments_do_not_crash():
    never = lambda r: httpx.Response(200, json={})
    out = run(api_with(never), "quote_renewal", {"drop_addons": [], "payment_plan": "annual", "discount_percent": "ten"})
    assert out["error"] == "BAD_ARGUMENTS" and out["detail"]


def test_quote_result_gains_spoken_fields():
    body = {"quoteId": "q", "annualPremium": 16350, "instalments": 4, "perInstalment": 4088, "mustHandoff": False}
    out = run(api_with(lambda r: httpx.Response(200, json=body)), "quote_renewal",
              {"drop_addons": [], "payment_plan": "quarterly", "discount_percent": 0})
    assert out["spoken"] == {
        "annualPremium": "sixteen thousand three hundred and fifty rupees",
        "perInstalment": "four thousand and eighty-eight rupees",
    }
    opts = {"paymentPlans": ["annual"], "removableAddons": [{"code": "OPD", "name": "x", "saving": 1000}]}
    out = run(api_with(lambda r: httpx.Response(200, json=opts)), "list_allowed_options", {})
    assert out["spoken"]["addonSavings"] == {"OPD": "one thousand rupees"}
    pol = {"lastPremium": 15000, "renewalPremium": 18450}
    out = run(api_with(lambda r: httpx.Response(200, json=pol)), "get_policy", {})
    assert out["spoken"]["renewalPremium"] == "eighteen thousand four hundred and fifty rupees"


def test_quote_defaults_plan_and_addons_when_missing_or_empty():
    bodies = []

    def handler(r):
        bodies.append(json.loads(r.content))
        return httpx.Response(200, json={"quoteId": "q"})

    api = api_with(handler)
    run(api, "quote_renewal", {"discount_percent": 1})
    run(api, "quote_renewal", {"payment_plan": "", "drop_addons": [], "discount_percent": 1})
    assert bodies == [{"dropAddons": [], "paymentPlan": "annual", "discountPercent": 1}] * 2


@pytest.mark.parametrize("bad", [f"{CALL}#", "../x", f"{CALL}/../{CALL}", f"{{{CALL}}}", CALL.replace("-", ""), ""])
def test_api_refuses_a_non_uuid_call_id_before_any_request(bad):
    seen = []
    api = api_with(lambda r: seen.append(r) or httpx.Response(200, json={}))
    with pytest.raises(InvalidCallId):
        asyncio.run(api.policy(bad))
    with pytest.raises(InvalidCallId):
        asyncio.run(api.call(bad))
    assert seen == []


def test_tool_with_a_non_uuid_call_id_never_reaches_the_api():
    seen = []
    api = api_with(lambda r: seen.append(r) or httpx.Response(200, json={"holderName": "Meera"}))
    result = asyncio.run(run_tool(api, f"{CALL}#", "get_policy", {}))
    assert result["error"] == "BAD_ARGUMENTS"
    assert seen == []


def test_handoff_callback_time_is_optional_and_nullable():
    schema = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == "handoff_to_human")["function"]["parameters"]
    assert schema["properties"]["callback_time"]["type"] == ["string", "null"]
    assert "callback_time" not in schema["required"]


@pytest.mark.parametrize("args", [{"reason": "death", "callback_time": None}, {"reason": "death"}])
def test_handoff_without_callback_time_omits_callback_at(args):
    seen = []
    api = api_with(lambda r: seen.append(json.loads(r.content)) or httpx.Response(200, json={"queued": True}))
    run(api, "handoff_to_human", args)
    assert seen == [{"reason": "death"}]


def test_refused_discount_says_premium_is_unchanged_with_the_policy_figure():
    def handler(r):
        if r.url.path.endswith("/policy"):
            return httpx.Response(200, json={"renewalPremium": 18450, "lastPremium": 15120})
        return problem(422, "OUTSIDE_PLAYBOOK")

    api, memory = api_with(handler), {}
    asyncio.run(run_tool(api, CALL, "get_policy", {}, memory))
    out = asyncio.run(run_tool(api, CALL, "quote_renewal", {"discount_percent": 20}, memory))
    assert out["error"] == "OUTSIDE_PLAYBOOK"
    assert out["note"] == ("No discount was applied. The premium is unchanged at eighteen thousand four hundred and "
                           "fifty rupees. Do not state or imply any discounted amount.")


def test_refused_discount_without_a_known_premium_omits_the_figure():
    out = run(api_with(lambda r: problem(422, "OUTSIDE_PLAYBOOK")), "quote_renewal", {"discount_percent": 20})
    assert out["note"] == ("No discount was applied. The premium is unchanged. "
                           "Do not state or imply any discounted amount.")
    other = run(api_with(lambda r: problem(422, "INVALID_OPTION")), "quote_renewal", {"discount_percent": 0})
    assert "note" not in other
