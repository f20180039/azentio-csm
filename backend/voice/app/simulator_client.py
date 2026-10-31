import httpx

from .api_client import ApiUnavailable
from .config import Settings

SESSION_HEADER = "X-Customer-Session"


class SimulatorClient:
    """The bank simulator (loan origination, loan management, core banking, CSM, insurance, FAQ). Client errors come back as
    {"error": CODE, ...} so the agent can explain them; only an unreachable simulator raises ApiUnavailable."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(base_url=settings.simulator_base.rstrip("/"), timeout=5.0, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _send(self, method: str, path: str, session: str | None = None, body: dict | None = None,
                    params: dict | None = None) -> dict:
        headers = {SESSION_HEADER: session} if session else {}
        try:
            resp = await self._client.request(method, path, json=body, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise ApiUnavailable(str(e)) from e
        if resp.status_code >= 500:
            raise ApiUnavailable(f"{resp.status_code} from {path}")
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            return {**data, "error": data.get("error") or f"HTTP_{resp.status_code}", "status": resp.status_code}
        return data

    async def verify(self, mobile: str, dob: str, call_id: str) -> dict:
        return await self._send("POST", "/verify", body={"mobile": mobile, "dob": dob, "call_id": call_id})

    async def applications(self, session: str) -> dict:
        return await self._send("GET", "/los/applications", session)

    async def loans(self, session: str, product_type: str | None = None) -> dict:
        return await self._send("GET", "/lms/loans", session, params={"type": product_type} if product_type else None)

    async def schedule(self, session: str, loan_id: str) -> dict:
        return await self._send("GET", f"/lms/loans/{loan_id}/schedule", session)

    async def accounts(self, session: str) -> dict:
        return await self._send("GET", "/cbs/accounts", session)

    async def transactions(self, session: str, status: str | None = None, ref: str | None = None, limit: int = 10) -> dict:
        params = {k: v for k, v in {"status": status, "ref": ref, "limit": limit}.items() if v}
        return await self._send("GET", "/cbs/transactions", session, params=params)

    async def tickets(self, session: str) -> dict:
        return await self._send("GET", "/csm/tickets", session)

    async def ticket(self, session: str, ref: str) -> dict:
        return await self._send("GET", f"/csm/tickets/{ref}", session)

    async def create_ticket(self, session: str, category: str, summary: str, details: dict, call_id: str) -> dict:
        body = {"category": category, "summary": summary, "details": details, "call_id": call_id}
        return await self._send("POST", "/csm/tickets", session, body=body)

    async def complaint(self, session: str, category: str, description: str, severity: str, call_id: str) -> dict:
        body = {"category": category, "description": description, "severity": severity, "call_id": call_id}
        return await self._send("POST", "/csm/complaints", session, body=body)

    async def routed(self, query_text: str, reason: str, call_id: str, customer_ref: str | None) -> dict:
        body = {"query_text": query_text, "reason": reason, "call_id": call_id, "customer_ref": customer_ref}
        return await self._send("POST", "/csm/routed", body=body)

    async def escalation(self, session: str | None, reason: str, summary: str, call_id: str) -> dict:
        return await self._send("POST", "/csm/escalations", session, body={"reason": reason, "summary": summary, "call_id": call_id})

    async def policies(self, session: str) -> dict:
        return await self._send("GET", "/insurance/policies", session)

    async def claims(self, session: str) -> dict:
        return await self._send("GET", "/insurance/claims", session)

    async def faq(self, query: str, limit: int = 3) -> dict:
        return await self._send("GET", "/faq/search", params={"q": query, "limit": limit})
