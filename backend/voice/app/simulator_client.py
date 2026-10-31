from enum import StrEnum

import httpx

from .api_client import ApiUnavailable
from .config import Settings
from .vocab import HTTP_ERROR_PREFIX

SESSION_HEADER = "X-Customer-Session"


class SimPath(StrEnum):
    """The bank simulator's endpoints, relative to SIMULATOR_BASE."""
    VERIFY = "/verify"
    LOS_APPLICATIONS = "/los/applications"
    LMS_LOANS = "/lms/loans"
    CBS_ACCOUNTS = "/cbs/accounts"
    CBS_TRANSACTIONS = "/cbs/transactions"
    CSM_TICKETS = "/csm/tickets"
    CSM_COMPLAINTS = "/csm/complaints"
    CSM_ROUTED = "/csm/routed"
    CSM_ESCALATIONS = "/csm/escalations"
    INSURANCE_POLICIES = "/insurance/policies"
    INSURANCE_CLAIMS = "/insurance/claims"
    FAQ_SEARCH = "/faq/search"


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
            return {**data, "error": data.get("error") or f"{HTTP_ERROR_PREFIX}{resp.status_code}", "status": resp.status_code}
        return data

    async def verify(self, mobile: str, dob: str, call_id: str, caller_ref: str | None = None) -> dict:
        body = {"mobile": mobile, "dob": dob, "call_id": call_id} | ({"caller_ref": caller_ref} if caller_ref else {})
        return await self._send("POST", SimPath.VERIFY, body=body)

    async def applications(self, session: str) -> dict:
        return await self._send("GET", SimPath.LOS_APPLICATIONS, session)

    async def loans(self, session: str, product_type: str | None = None) -> dict:
        return await self._send("GET", SimPath.LMS_LOANS, session, params={"type": product_type} if product_type else None)

    async def schedule(self, session: str, loan_id: str) -> dict:
        return await self._send("GET", f"{SimPath.LMS_LOANS}/{loan_id}/schedule", session)

    async def accounts(self, session: str) -> dict:
        return await self._send("GET", SimPath.CBS_ACCOUNTS, session)

    async def transactions(self, session: str, status: str | None = None, ref: str | None = None, limit: int = 10) -> dict:
        params = {k: v for k, v in {"status": status, "ref": ref, "limit": limit}.items() if v}
        return await self._send("GET", SimPath.CBS_TRANSACTIONS, session, params=params)

    async def tickets(self, session: str) -> dict:
        return await self._send("GET", SimPath.CSM_TICKETS, session)

    async def ticket(self, session: str, ref: str) -> dict:
        return await self._send("GET", f"{SimPath.CSM_TICKETS}/{ref}", session)

    async def complaint_status(self, session: str, ref: str) -> dict:
        return await self._send("GET", f"{SimPath.CSM_COMPLAINTS}/{ref}", session)

    async def create_ticket(self, session: str, category: str, summary: str, details: dict, call_id: str) -> dict:
        body = {"category": category, "summary": summary, "details": details, "call_id": call_id}
        return await self._send("POST", SimPath.CSM_TICKETS, session, body=body)

    async def complaint(self, session: str, category: str, description: str, severity: str, call_id: str,
                        original_statement: str | None = None, related_ref: str | None = None) -> dict:
        """`description` is the agent's structured summary; `original_statement` the caller's own words and
        `related_ref` the account, loan or transaction the complaint is about (Level 2)."""
        body = {"category": category, "description": description, "severity": severity, "call_id": call_id,
                "original_statement": original_statement, "related_ref": related_ref}
        return await self._send("POST", SimPath.CSM_COMPLAINTS, session, body=body)

    async def routed(self, query_text: str, reason: str, call_id: str, customer_ref: str | None) -> dict:
        body = {"query_text": query_text, "reason": reason, "call_id": call_id, "customer_ref": customer_ref}
        return await self._send("POST", SimPath.CSM_ROUTED, body=body)

    async def escalation(self, session: str | None, reason: str, summary: str, call_id: str,
                         category: str | None = None, related_refs: list[str] | None = None) -> dict:
        """`category` is the escalation trigger; `related_refs` the records raised on this call it concerns (Level 2)."""
        body = {"reason": reason, "summary": summary, "call_id": call_id, "category": category, "related_refs": list(related_refs or [])}
        return await self._send("POST", SimPath.CSM_ESCALATIONS, session, body=body)

    async def policies(self, session: str) -> dict:
        return await self._send("GET", SimPath.INSURANCE_POLICIES, session)

    async def claims(self, session: str) -> dict:
        return await self._send("GET", SimPath.INSURANCE_CLAIMS, session)

    async def faq(self, query: str, limit: int = 3) -> dict:
        return await self._send("GET", SimPath.FAQ_SEARCH, params={"q": query, "limit": limit})
