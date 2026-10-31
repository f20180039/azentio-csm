from datetime import datetime, timezone
from uuid import UUID

import httpx

from .config import Settings
from .vocab import Channel, Outcome, TurnRole

MUST_HANDOFF_CODES = {"MUST_HANDOFF", "VERIFY_LOCKED"}
SUPPORT_CALLS = "/support/calls"
SUPPORT_LESSONS = "/support/lessons"


class ApiUnavailable(Exception):
    pass


class InvalidCallId(ValueError):
    pass


class RenewalsApi:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url=settings.api_base.rstrip("/"),
            auth=(settings.api_user, settings.api_password),
            timeout=5.0,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _send(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            resp = await self._client.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise ApiUnavailable(str(e)) from e
        if resp.status_code >= 500:
            raise ApiUnavailable(f"{resp.status_code} from {path}")
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail") or resp.reason_phrase
            except ValueError:
                detail = resp.reason_phrase
            return {"error": detail, "status": resp.status_code, "mustHandoff": detail in MUST_HANDOFF_CODES}
        return resp.json() if resp.content else {}

    @staticmethod
    def _p(call_id: str, tail: str = "") -> str:
        try:
            canonical = str(UUID(str(call_id)))
        except ValueError as e:
            raise InvalidCallId(f"call id is not a UUID: {call_id!r}") from e
        if canonical != str(call_id).lower():
            raise InvalidCallId(f"call id is not a canonical UUID: {call_id!r}")
        return f"/renewals/calls/{canonical}{tail}"

    async def verify(self, call_id: str, dob: str) -> dict:
        return await self._send("POST", self._p(call_id, "/verify"), {"dateOfBirth": dob})

    async def policy(self, call_id: str) -> dict:
        return await self._send("GET", self._p(call_id, "/policy"))

    async def options(self, call_id: str) -> dict:
        return await self._send("GET", self._p(call_id, "/options"))

    async def quote(self, call_id: str, drop_addons: list[str], payment_plan: str, discount_percent: int) -> dict:
        body = {"dropAddons": drop_addons, "paymentPlan": payment_plan, "discountPercent": discount_percent}
        return await self._send("POST", self._p(call_id, "/quote"), body)

    async def payment_link(self, call_id: str, quote_id: str) -> dict:
        return await self._send("POST", self._p(call_id, "/payment-link"), {"quoteId": quote_id})

    async def handoff(self, call_id: str, reason: str, callback_at: str | None = None) -> dict:
        body = {"reason": reason} if callback_at is None else {"reason": reason, "callbackAt": callback_at}
        return await self._send("POST", self._p(call_id, "/handoff"), body)

    async def turn(self, call_id: str, role: str, text: str) -> dict:
        at = datetime.now(timezone.utc).isoformat()
        return await self._send("POST", self._p(call_id, "/turns"), {"role": role, "text": text, "at": at})

    async def end(self, call_id: str) -> dict:
        return await self._send("POST", self._p(call_id, "/end"))

    async def call(self, call_id: str) -> dict:
        return await self._send("GET", self._p(call_id))


class SupportCallsApi:
    """Spring's support call records: one call, its turns in order, and per-turn metadata for the operator panel."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url=settings.api_base.rstrip("/"), auth=(settings.api_user, settings.api_password), timeout=5.0, transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _send(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            resp = await self._client.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise ApiUnavailable(str(e)) from e
        if resp.status_code >= 400:
            raise ApiUnavailable(f"{resp.status_code} from {path}")
        try:
            return resp.json() if resp.content else {}
        except ValueError:
            return {}

    async def start(self, channel: Channel) -> str:
        return (await self._send("POST", SUPPORT_CALLS, {"channel": channel}))["id"]

    async def turn(self, call_id: str, role: TurnRole, text: str, meta: dict) -> dict:
        at = datetime.now(timezone.utc).isoformat()
        return await self._send("POST", f"{SUPPORT_CALLS}/{call_id}/turns", {"role": role, "text": text, "at": at, "meta": meta})

    async def patch_meta(self, call_id: str, seq: int, meta: dict) -> dict:
        return await self._send("PATCH", f"{SUPPORT_CALLS}/{call_id}/turns/{seq}/meta", meta)

    async def end(self, call_id: str, outcome: Outcome | str) -> dict:
        return await self._send("POST", f"{SUPPORT_CALLS}/{call_id}/end", {"outcome": outcome})

    async def rating(self, call_id: str, score: int, comment: str | None) -> dict:
        return await self._send("POST", f"{SUPPORT_CALLS}/{call_id}/rating", {"score": score, "comment": comment, "source": "VOICE"})

    async def active_lessons(self) -> list[str]:
        out = await self._send("GET", f"{SUPPORT_LESSONS}?active=true")
        return [i["text"] for i in out.get("items", []) if i.get("text")]
