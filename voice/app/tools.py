from .api_client import RenewalsApi
from .spoken import spoken_inr


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        },
    }


TOOL_SCHEMAS: list[dict] = [
    _tool(
        "verify_identity",
        "Check the customer's date of birth. Must succeed before any policy detail is shared.",
        {"date_of_birth": {"type": "string", "description": "Date of birth as YYYY-MM-DD"}},
        ["date_of_birth"],
    ),
    _tool("get_policy", "Fetch the verified customer's policy and renewal premium."),
    _tool("list_allowed_options", "List the payment plans, removable add-ons and maximum discount on offer."),
    _tool(
        "quote_renewal",
        "Price a renewal using only options returned by list_allowed_options.",
        {
            "drop_addons": {"type": "array", "items": {"type": "string"}, "description": "Add-on codes to remove"},
            "payment_plan": {"type": "string", "description": "A payment plan from the allowed options"},
            "discount_percent": {"type": "integer", "description": "Discount percent, 0 if none"},
        },
        ["drop_addons", "payment_plan", "discount_percent"],
    ),
    _tool(
        "send_payment_link",
        "Send the payment link for a quote to the customer's registered mobile.",
        {"quote_id": {"type": "string", "description": "quoteId returned by quote_renewal"}},
        ["quote_id"],
    ),
    _tool(
        "handoff_to_human",
        "Transfer the customer to a human agent, optionally with a callback time.",
        {
            "reason": {"type": "string", "description": "Why the call is being handed off"},
            "callback_time": {"type": "string", "description": "Optional ISO-8601 callback time"},
        },
        ["reason"],
    ),
    _tool("end_call", "End the call once the customer is done."),
]


async def run_tool(api: RenewalsApi, call_id: str, name: str, args: dict) -> dict:
    try:
        return _add_spoken(await _dispatch(api, call_id, name, args))
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        return {"error": "BAD_ARGUMENTS", "detail": f"{type(e).__name__}: {e}"[:200]}


async def _dispatch(api: RenewalsApi, call_id: str, name: str, args: dict) -> dict:
    match name:
        case "verify_identity":
            return await api.verify(call_id, args["date_of_birth"])
        case "get_policy":
            return await api.policy(call_id)
        case "list_allowed_options":
            return await api.options(call_id)
        case "quote_renewal":
            return await api.quote(
                call_id,
                args.get("drop_addons") or [],
                args["payment_plan"],
                int(args.get("discount_percent") or 0),
            )
        case "send_payment_link":
            return await api.payment_link(call_id, args["quote_id"])
        case "handoff_to_human":
            return await api.handoff(call_id, args["reason"], args.get("callback_time"))
        case "end_call":
            return await api.end(call_id)
        case _:
            return {"error": "UNKNOWN_TOOL"}


def _add_spoken(result: dict) -> dict:
    if "error" in result:
        return result
    spoken = {
        k: spoken_inr(result[k])
        for k in ("renewalPremium", "lastPremium", "annualPremium", "perInstalment")
        if isinstance(result.get(k), int) and not isinstance(result.get(k), bool)
    }
    savings = {
        a["code"]: spoken_inr(a["saving"])
        for a in result.get("removableAddons") or []
        if isinstance(a.get("saving"), int)
    }
    if savings:
        spoken["addonSavings"] = savings
    return {**result, "spoken": spoken} if spoken else result
