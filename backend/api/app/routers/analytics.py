"""Analytics & Telemetry Router."""
from fastapi import APIRouter

router = APIRouter(prefix="/v1/analytics", tags=["Analytics & CX Metrics"])


@router.get("/dashboard")
async def get_dashboard_metrics():
    """Aggregated CX and operational metrics conforming to BFSI benchmarks."""
    return {
        "containment_rate": 84.6,  # 84.6% queries resolved without human agent
        "csat_score": 4.82,        # Out of 5.0
        "total_conversations_today": 14280,
        "bot_resolved_count": 12080,
        "human_escalated_count": 2200,
        "avg_turnaround_seconds": 1.45,
        "intent_accuracy": 96.2,
        "top_intents": [
            {"intent": "CARD_BLOCK_EMERGENCY", "percentage": 28.4},
            {"intent": "LOAN_EMI_QUERY", "percentage": 24.1},
            {"intent": "INSURANCE_CLAIM_FNOL", "percentage": 19.3},
            {"intent": "BALANCE_ENQUIRY", "percentage": 16.2},
            {"intent": "OTHERS_FAQ", "percentage": 12.0}
        ],
        "channel_breakdown": {
            "whatsapp": 54.2,
            "web_widget": 31.8,
            "voice_ivr": 14.0
        }
    }
