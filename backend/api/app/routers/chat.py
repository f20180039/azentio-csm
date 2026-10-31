"""Omnichannel Conversational AI Engine & LLM Orchestrator Router."""
import re
from datetime import datetime
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.security.auth import TokenData, get_current_user
from app.security.pii import PIIRedactor
from app.security.audit import audit_ledger

router = APIRouter(prefix="/v1/chat", tags=["Conversational AI Engine"])

# Ephemeral in-memory sessions
SESSIONS_DB: dict[str, dict[str, Any]] = {}


class ChatMessageRequest(BaseModel):
    session_id: str
    channel: str = "WEB"  # "WEB", "WHATSAPP", "VOICE"
    text: str
    language: str = "en"  # "en", "hi", "hinglish"
    metadata: dict[str, Any] = {}


class ChatMessageResponse(BaseModel):
    session_id: str
    response_text: str
    intent: str
    sentiment: str
    action_required: str | None = None
    step_up_needed: bool = False
    audit_hash: str
    suggested_quick_replies: list[str] = []


def _detect_sentiment(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in ["stolen", "loss", "lost", "fraud", "panic", "urgent", "broken", "accident"]):
        return "URGENT"
    if any(w in lower for w in ["angry", "bad", "cheat", "scam", "worst", "unhappy", "delay"]):
        return "NEGATIVE"
    return "NEUTRAL"


@router.post("/message", response_model=ChatMessageResponse)
async def process_chat_message(req: ChatMessageRequest, user: Annotated[TokenData, Depends(get_current_user)]):
    # 1. PII Redaction
    redaction = PIIRedactor.redact(req.text)
    clean_text = redaction.redacted_text
    lower_text = clean_text.lower()

    # 2. Retrieve or initialize session state
    session = SESSIONS_DB.setdefault(req.session_id, {
        "id": req.session_id,
        "channel": req.channel,
        "step": "INIT",
        "card_target": None,
        "handoff": False,
        "messages": []
    })

    sentiment = _detect_sentiment(clean_text)

    # 3. Intent Detection & Deterministic DAG Execution
    intent = "FAQ_GENERAL"
    response_text = ""
    action_required = None
    step_up_needed = False
    quick_replies: list[str] = []

    # Check for live human handoff request
    if any(w in lower_text for w in ["agent", "human", "representative", "manager", "support person"]):
        intent = "HUMAN_HANDOFF"
        session["handoff"] = True
        response_text = "I am transferring you to our senior BFSI relationship specialist right away with the full conversation history. Please hold on."
        quick_replies = ["Cancel Handoff"]

    # Session State Priority 1: Card Selection
    elif session.get("step") == "CARD_SELECTION" and ("4102" in lower_text or "platinum" in lower_text or "9018" in lower_text):
        intent = "CARD_BLOCK_STEP_UP"
        session["step"] = "AWAITING_OTP"
        session["card_target"] = "CRD_4102" if "4102" in lower_text or "platinum" in lower_text else "CRD_9018"
        step_up_needed = True
        action_required = "STEP_UP_OTP"
        response_text = (
            "Understood. For your protection, an emergency confirmation OTP has been dispatched "
            "to your registered mobile ending in 8821. Please enter the 6-digit OTP to block Platinum 4102."
        )

    # Session State Priority 2: Awaiting OTP
    elif session.get("step") == "AWAITING_OTP" and re.search(r"\b\d{6}\b", req.text):
        otp = re.search(r"\b\d{6}\b", req.text).group(0)
        if otp == "592810":
            intent = "CARD_BLOCK_CONFIRMED"
            session["step"] = "COMPLETED"
            response_text = (
                "✅ Your Platinum Rewards Card ending in 4102 is PERMANENTLY BLOCKED.\n"
                "Ref ID: BLK-20261031-4102.\n\n"
                "Would you like a replacement card dispatched to your registered address in Bangalore?"
            )
            quick_replies = ["Yes, dispatch replacement", "No, I'll order later"]
        else:
            response_text = "The OTP entered was incorrect. Please try again with 592810 (demo OTP)."

    # Initial Triggers: Journey 1: Card Block
    elif any(w in lower_text for w in ["block", "stolen", "lost card", "freeze card"]):
        intent = "CARD_BLOCK_INIT"
        session["step"] = "CARD_SELECTION"
        response_text = (
            "I understand. Let's protect your card right away.\n"
            "I found 2 cards linked to your account:\n"
            "1. Platinum Rewards ending in 4102\n"
            "2. Regalia Forex ending in 9018\n\n"
            "Which card would you like to block?"
        )
        quick_replies = ["Platinum 4102", "Regalia 9018", "Block All Cards"]

    # Journey 2: Loan EMI Query & Prepayment
    elif any(w in lower_text for w in ["emi", "loan", "home loan"]):
        intent = "LOAN_EMI_QUERY"
        response_text = (
            "Your upcoming Home Loan EMI details (Account #HL-901823):\n"
            "• Amount Due: ₹42,650\n"
            "• Due Date: 05 November 2026\n"
            "• Auto-Debit Status: Active (HDFC Bank ending in 3421)\n\n"
            "You can choose an option below:"
        )
        quick_replies = ["Pay Now", "Calculate Prepayment", "Download Statement"]

    # Journey 3: Insurance Claim FNOL
    elif any(w in lower_text for w in ["claim", "accident", "damage", "scratch", "fnol"]):
        intent = "INSURANCE_CLAIM_FNOL"
        response_text = (
            "I'm sorry to hear about the incident. Please confirm everyone is safe.\n\n"
            "I found active Policy #MOT-2024-8812 for Hyundai Creta (MH 02 EE 4091).\n"
            "Please upload photos of the damage or describe the incident location to initiate instant FNOL."
        )
        quick_replies = ["Upload Photos", "Find Cashless Garage", "Request Towing"]

    else:
        # Default RAG & Policy FAQ Fallback with compliance boundary
        intent = "KNOWLEDGE_RAG"
        response_text = (
            "Welcome to FinPulse AI Banking Assistant. I can assist you with:\n"
            "• Instant Card Block & Freeze\n"
            "• Loan EMI Status & Prepayment Savings Calculator\n"
            "• Insurance Claims (FNOL) & Policy Renewals\n"
            "• Account Balances & Transactions"
        )
        quick_replies = ["Block My Card", "Check Loan EMI", "File a Claim", "Speak with Agent"]

    # 4. Cryptographic Audit Recording
    audit_entry = audit_ledger.record(
        actor=user.username,
        action="CHAT_TURN",
        entity_ref=req.session_id,
        payload={
            "intent": intent,
            "sentiment": sentiment,
            "pii_detected": redaction.pii_detected,
            "channel": req.channel
        }
    )

    return ChatMessageResponse(
        session_id=req.session_id,
        response_text=response_text,
        intent=intent,
        sentiment=sentiment,
        action_required=action_required,
        step_up_needed=step_up_needed,
        audit_hash=audit_entry.hash,
        suggested_quick_replies=quick_replies
    )


@router.post("/handoff")
async def trigger_handoff(session_id: str, reason: str = "CUSTOMER_REQUEST"):
    session = SESSIONS_DB.get(session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    session["handoff"] = True
    audit_ledger.record(actor="SYSTEM", action="AGENT_ESCALATION", entity_ref=session_id, payload={"reason": reason})
    return {"status": "ESCALATED", "session_id": session_id, "assigned_queue": "BFSI_TIER_2_PRIORITY"}
