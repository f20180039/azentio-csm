"""Twilio phone calls: outbound dials and inbound support calls, both streaming the call audio to a websocket."""

import base64
import hashlib
import hmac
import re
from dataclasses import dataclass
from uuid import UUID
from xml.sax.saxutils import escape, quoteattr

import httpx

from .config import Settings
from .vocab import Route

TWILIO_API = "https://api.twilio.com"
PENDING_TTL_SECS = 120.0
TUNNEL_CHECK_SECS = 2.0
HANDOFF_TRANSFER_DELAY_SECS = 6.0  # time for the agent to say it is connecting them
_NUMBER = re.compile(r"\+\d{8,15}")


class DialError(Exception):
    pass


@dataclass(frozen=True)
class StreamStart:
    stream_sid: str
    call_sid: str
    call_id: str


def configured(s: Settings) -> bool:
    return bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_from and s.public_base_url and s.twilio_allowed_to)


def inbound_configured(s: Settings) -> bool:
    """Enough to answer calls to the Twilio number: picking up needs no allow-list or caller id."""
    return bool(s.twilio_account_sid and s.twilio_auth_token and s.public_base_url)


def signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Twilio's X-Twilio-Signature: HMAC-SHA1 over the full URL followed by every POST param, sorted by name."""
    payload = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()).decode()


def signature_valid(auth_token: str, url: str, params: dict[str, str], given: str | None) -> bool:
    return bool(auth_token and given) and hmac.compare_digest(signature(auth_token, url, params), given)


def mask(number: str) -> str:
    digits = number.lstrip("+")
    country = digits[:-10] if len(digits) > 10 else ""
    return f"{'+' + country + ' ' if country else ''}••••• •{digits[-4:]}"


def mask_numbers(text: str) -> str:
    return _NUMBER.sub(lambda m: mask(m.group()), text)


async def tunnel_up(public_base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Twilio fetches nothing until the call connects, so a dead tunnel would only show as a silent call."""
    try:
        async with httpx.AsyncClient(timeout=TUNNEL_CHECK_SECS, transport=transport) as client:
            r = await client.get(public_base_url.rstrip("/") + "/health")
        return r.status_code == 200 and r.json().get("status") == "ok"
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


def twiml(public_base_url: str, call_id: str, stream_path: str = Route.TWILIO_WS) -> str:
    base = public_base_url.rstrip("/")
    ws = "wss://" + base.removeprefix("https://") if base.startswith("https://") else "ws://" + base.removeprefix("http://")
    return (
        f"<Response><Connect><Stream url={quoteattr(ws + stream_path)}>"
        f"<Parameter name=\"callId\" value={quoteattr(call_id)}/>"
        "</Stream></Connect></Response>"
    )


def parse_start(msg: dict) -> StreamStart:
    if msg.get("event") != "start":
        raise ValueError("expected a start message")
    start = msg.get("start") or {}
    stream_sid, call_sid = start.get("streamSid"), start.get("callSid")
    if not stream_sid or not call_sid:
        raise ValueError("start message without streamSid or callSid")
    return StreamStart(str(stream_sid), str(call_sid), str(UUID(str((start.get("customParameters") or {}).get("callId")))))


async def dial(s: Settings, call_id: str, to: str, transport: httpx.AsyncBaseTransport | None = None,
               twiml_path: str = Route.TWILIO_TWIML) -> str:
    async with httpx.AsyncClient(
        base_url=TWILIO_API, auth=(s.twilio_account_sid, s.twilio_auth_token), timeout=15.0, transport=transport
    ) as client:
        try:
            r = await client.post(
                f"/2010-04-01/Accounts/{s.twilio_account_sid}/Calls.json",
                data={"To": to, "From": s.twilio_from,
                      "Url": f"{s.public_base_url.rstrip('/')}{twiml_path}?callId={call_id}"},
            )
        except httpx.HTTPError as e:
            raise DialError(f"Twilio unreachable: {type(e).__name__}") from None
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 300 or not body.get("sid"):
        raise DialError(f"Twilio {r.status_code} {body.get('code', '')}: {body.get('message', 'no call created')}".strip())
    return str(body["sid"])


TRANSFER_SAY = "Connecting you to a colleague now. Please stay on the line."


def transfer_twiml(to: str) -> str:
    return f"<Response><Say>{escape(TRANSFER_SAY)}</Say><Dial>{escape(to)}</Dial></Response>"


async def transfer(s: Settings, call_sid: str, to: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
    """Hands a live phone call to a person: Twilio replaces the call's instructions with a dial to `to`, which also ends
    the media stream, so the agent's pipeline closes on its own."""
    async with httpx.AsyncClient(
        base_url=TWILIO_API, auth=(s.twilio_account_sid, s.twilio_auth_token), timeout=15.0, transport=transport
    ) as client:
        try:
            r = await client.post(f"/2010-04-01/Accounts/{s.twilio_account_sid}/Calls/{call_sid}.json", data={"Twiml": transfer_twiml(to)})
        except httpx.HTTPError as e:
            raise DialError(f"Twilio unreachable: {type(e).__name__}") from None
    if r.status_code >= 300:
        raise DialError(f"Twilio {r.status_code}: transfer to {mask(to)} refused")
