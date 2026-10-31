"""Visual No-Code Flow Builder Router."""
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.security.auth import TokenData, get_current_user
from app.security.audit import audit_ledger

router = APIRouter(prefix="/v1/flows", tags=["Flow Builder"])

SAMPLE_FLOWS = [
    {
        "id": "flow-card-block-v1",
        "name": "Emergency Card Freeze & Replacement",
        "trigger_intent": "CARD_BLOCK",
        "nodes": [
            {"id": "node-1", "type": "TRIGGER", "label": "User requests card block"},
            {"id": "node-2", "type": "API_FETCH", "label": "Fetch active cards via CBS", "endpoint": "/v1/cbs/cards"},
            {"id": "node-3", "type": "USER_SELECT", "label": "Prompt card selection"},
            {"id": "node-4", "type": "SECURITY_GATE", "label": "Step-up OTP verification"},
            {"id": "node-5", "type": "API_ACTION", "label": "Execute permanent freeze", "endpoint": "/v1/cbs/cards/block"},
            {"id": "node-6", "type": "AUDIT_LOG", "label": "Record cryptographic hash"}
        ],
        "is_published": True,
        "version": 1
    },
    {
        "id": "flow-loan-prepay-v1",
        "name": "Loan EMI & Prepayment Calculator",
        "trigger_intent": "LOAN_PREPAY",
        "nodes": [
            {"id": "node-1", "type": "TRIGGER", "label": "User queries EMI / prepayment"},
            {"id": "node-2", "type": "API_FETCH", "label": "Fetch loan details", "endpoint": "/v1/cbs/loans/{id}"},
            {"id": "node-3", "type": "FINTECH_MATH", "label": "Compute interest savings & tenor reduction"},
            {"id": "node-4", "type": "PAYMENT_PROMPT", "label": "Generate UPI / NetBanking link"}
        ],
        "is_published": True,
        "version": 1
    }
]


class FlowPublishRequest(BaseModel):
    name: str
    trigger_intent: str
    nodes: list[dict[str, Any]]


@router.get("")
async def list_flows():
    return {"flows": SAMPLE_FLOWS}


@router.post("")
async def create_flow(req: FlowPublishRequest, user: Annotated[TokenData, Depends(get_current_user)]):
    new_flow = {
        "id": f"flow-{len(SAMPLE_FLOWS)+1}",
        "name": req.name,
        "trigger_intent": req.trigger_intent,
        "nodes": req.nodes,
        "is_published": True,
        "version": 1
    }
    SAMPLE_FLOWS.append(new_flow)
    audit_ledger.record(actor=user.username, action="FLOW_PUBLISHED", entity_ref=new_flow["id"], payload={"name": req.name})
    return new_flow
