"""Outbound phone calls: Twilio dials the customer and streams the call audio to /ws/twilio."""

import re
from dataclasses import dataclass
from uuid import UUID
from xml.sax.saxutils import quoteattr

import httpx

from .config import Settings

TWILIO_API = "https://api.twilio.com"
PENDING_TTL_SECS = 120.0
TUNNEL_CHECK_SECS = 2.0
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


def twiml(public_base_url: str, call_id: str) -> str:
    base = public_base_url.rstrip("/")
    ws = "wss://" + base.removeprefix("https://") if base.startswith("https://") else "ws://" + base.removeprefix("http://")
    return (
        f"<Response><Connect><Stream url={quoteattr(ws + '/ws/twilio')}>"
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


async def dial(s: Settings, call_id: str, to: str, transport: httpx.AsyncBaseTransport | None = None) -> str:
    async with httpx.AsyncClient(
        base_url=TWILIO_API, auth=(s.twilio_account_sid, s.twilio_auth_token), timeout=15.0, transport=transport
    ) as client:
        try:
            r = await client.post(
                f"/2010-04-01/Accounts/{s.twilio_account_sid}/Calls.json",
                data={"To": to, "From": s.twilio_from, "Method": "POST",
                      "Url": f"{s.public_base_url.rstrip('/')}/twilio/twiml?callId={call_id}"},
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
