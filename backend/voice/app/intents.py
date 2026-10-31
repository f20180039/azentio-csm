"""Intent labels for a customer turn: Groq in JSON mode, keyword rules when the LLM is slow, failing or keyless."""

import asyncio
import json
import re
from dataclasses import dataclass
from enum import StrEnum

import httpx
from loguru import logger

from .llm_chain import PROVIDERS
from .vocab import IntentSource


class Intent(StrEnum):
    LOAN_APPLICATION = "LOAN_APPLICATION"
    REPAYMENT = "REPAYMENT"
    ACCOUNT = "ACCOUNT"
    SERVICE_REQUEST = "SERVICE_REQUEST"
    PRODUCT_INFO = "PRODUCT_INFO"
    COMPLAINT = "COMPLAINT"
    INSURANCE = "INSURANCE"
    IDENTITY = "IDENTITY"
    HUMAN_AGENT = "HUMAN_AGENT"
    UNSUPPORTED = "UNSUPPORTED"
    UNCLEAR = "UNCLEAR"
    CHITCHAT = "CHITCHAT"


@dataclass(frozen=True)
class IntentResult:
    intents: list[Intent]
    confidence: float
    source: IntentSource


def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_BIRTH_YEAR = r"(?:19\d{2}|20[01]\d)"

_RULES: dict[Intent, re.Pattern] = {
    Intent.LOAN_APPLICATION: _rx(
        r"\bloan\s+application", r"\bapplication\s+(?:status|ref|reference|number|no)\b",
        r"\bmy\s+application\b", r"\bappl(?:ied|ication)\b.{0,25}\bloan\b",
        r"\bloan\b.{0,15}\b(?:status|sanction(?:ed)?|approved|disburs\w*)\b",
        r"\b(?:status|sanction|approval|disbursal|disbursement)\s+of\s+(?:my\s+)?(?:\w+\s+)?loan\b(?!\s+statement)",
        r"\bAPP[\s-]?\d{3,}\b", r"\bLA[\s-]?\d{3,}\b", r"\bapplication\b.{0,25}\b(?:next\s+step|update|stage)\b",
        r"\b(?:submitted|applied)\b.{0,40}\bloan\b", r"\bloan\s+papers?\b"),
    Intent.REPAYMENT: _rx(
        r"\bemi\b", r"\bemis\b", r"\binstall?e?ments?\b", r"\bdue\s+date\b", r"\bdue\s+(?:amount|on)\b",
        r"\brepay\w*", r"\boverdue\b", r"\boutstanding\b", r"\bforeclos\w*", r"\bpre-?pay\w*",
        r"\bhow\s+much\b.{0,25}\bpay\b", r"\bpay\b.{0,15}\bnext\s+month\b", r"\bnext\s+(?:loan\s+)?payment\b",
        r"\bkitna\b.{0,20}\b(?:pay|bharna|dena)\b"),
    Intent.ACCOUNT: _rx(
        r"\bbalance\b", r"\btransactions?\b", r"\bmini\s+statement\b", r"\bdebited\b", r"\bcredited\b",
        r"\b(?:savings|current|salary|bank)\s+account\b", r"\baccount\s+(?:details|number|summary)\b",
        r"\bpaisa\b.{0,20}\b(?:kat|cut)\b", r"\bTXN[\s-]?\d{3,}\b", r"\btransfer\b.{0,30}\b(?:status|fail\w*|pending|happened|went|through|reflect\w*|stuck)\b", r"\bhappened\s+to\b.{0,15}\btransfer\b",
        r"\bpayment\b.{0,30}\b(?:posted|pending|status|go\s+through|gone\s+through)\b"),
    Intent.SERVICE_REQUEST: _rx(
        r"\bSR[\s-]?\d{3,}\b", r"\btickets?\b", r"\bservice\s+request\b", r"\brequest\s+(?:status|number|id)\b",
        r"\b(?<!mini\s)statement\b", r"\bnoc\b", r"\bno\s+objection\b", r"\b(?:interest|tax)\s+certificate\b",
        r"\b(?:change|update)\s+(?:my\s+)?(?:address|email|e-mail|mobile|phone|contact)\b",
        r"\bcheque\s*book\b", r"\b(?:block|replace|reissue)\b.{0,15}\bcard\b", r"\braise\b.{0,30}\brequest\b",
        r"\b(?:schedule|statement|change|document)\s+request\b", r"\baddress\s+change\b",
        r"\b(?:need|want|send|get|share|email)\b.{0,25}\b(?:repayment|loan)\s+schedule\b"),
    Intent.PRODUCT_INFO: _rx(
        r"\bdocuments?\b.{0,15}\b(?:for|required|needed|to)\b", r"\bdocuments?\s+(?:list|required)\b",
        r"\beligib\w*", r"\binterest\s+rates?\b", r"\brate\s+of\s+interest\b", r"\broi\b",
        r"\bhow\s+(?:do|can|to)\s+(?:i\s+)?apply\b", r"\bapply\s+for\b", r"\bwant\s+(?:a|to\s+take\s+a)\s+\w*\s*loan\b",
        r"\btenure\b", r"\bprocessing\s+fees?\b", r"\btell\s+me\s+about\b", r"\bfeatures\s+of\b",
        r"\b(?:fixed|recurring)\s+deposit\b", r"\bfd\s+rates?\b", r"\bloan\s+options\b", r"\bwhich\s+loan\b",
        r"\bhow\s+(?:do|can|to)\s+(?:i\s+)?(?:stop|start|set\s+up|cancel|foreclose|prepay|close|activate)\b",
        r"\b(?:branch|helpline|working|office|customer\s+care)\s+(?:hours|timings?)\b", r"\bgrace\s+period\b",
        r"\bwhat\s+(?:can|do)\s+you\s+(?:do|offer|help)", r"\bcapable\s+of\b", r"\bhow\s+can\s+you\s+help\b",
        r"\bservices\s+(?:do\s+you|you)\s+offer\b"),
    Intent.COMPLAINT: _rx(
        r"\bcomplain\w*", r"\bgrievance\b", r"\bfraud\w*", r"\bunauthori[sz]ed\b", r"\bdispute\b",
        r"\bfail(?:ed|ing|s)?\b", r"\bdeducted\s+twice\b", r"\bcharged\s+(?:twice|extra|wrongly)\b",
        r"\bwrong(?:ly)?\b", r"\bnot\s+(?:received|credited|refunded|reflect\w*|working|updated)\b",
        r"\brefund\b", r"\bdebited\s+but\b", r"\bpathetic\b", r"\bharass\w*", r"\bkat\s+gaya\b",
        r"\b(?:didn'?t|did\s+not|never)\s+(?:make|do|authori[sz]e)\b", r"\b(?:poor|bad|terrible|rude|slow)\s+(?:service|experience)\b",
        r"\bservice\b.{0,30}\b(?:poor|terrible|rude|very\s+slow)\b", r"\bincorrect\s+charge\b",
        r"\breport\b.{0,25}\b(?:charge|transaction|issue|fraud|problem)\b"),
    Intent.INSURANCE: _rx(
        r"\binsurance\b", r"\binsured\b", r"\bpolicy\b", r"\bpolicies\b", r"\bclaims?\b", r"\bpremium\b",
        r"\b(?:health|life|motor)\s+cover\b"),
    Intent.HUMAN_AGENT: _rx(
        r"\b(?:talk|speak|connect|transfer)\b.{0,15}\b(?:person|human|agent|someone|somebody|executive|"
        r"representative|manager|officer|staff)\b",
        r"\breal\s+(?:person|human)\b", r"\bhuman\s+agent\b", r"\bcustomer\s+care\s+executive\b",
        r"\bsupervisor\b", r"\b(?:get|need|want)\b.{0,25}\b(?:representative|executive|human|real\s+person)\b",
        r"\bcall\s+me\s+back\b", r"\bcall\s*back\b"),
    Intent.UNSUPPORTED: _rx(
        r"\bweather\b", r"\bflights?\b", r"\btrain\s+tickets?\b", r"\bhotel\b", r"\bmovies?\b", r"\bcricket\b",
        r"\bscore\b", r"\bjokes?\b", r"\brecipe\b", r"\bsongs?\b", r"\bnews\b", r"\bbook\s+(?:me\s+)?an?\s+(?:cab|taxi)\b",
        r"\bstocks?\b", r"\bshares?\s+(?:tips?|to\s+buy)\b", r"\bcrypto\w*", r"\bbitcoin\b",
        r"\b(?:transfer|send)\s+(?:rs\.?\s*|₹\s*|\d+\s*)?(?:money|funds|rupees|\d+)\b.{0,30}\bto\b",
        r"\b(?:transfer|send)\b.{0,20}\bto\s+(?:my\s+)?(?:friend|brother|sister|someone|wife|husband|mom|dad)\b",
        r"\blocker\b", r"\bdemat\b", r"\bforex\b", r"\bmutual\s+funds?\b", r"\bcredit\s+card\s+limit\b"),
}

_CHITCHAT = _rx(r"^\s*(?:ok(?:ay)?\s+)?(?:hi|hello|hey|hii+|namaste|good\s+(?:morning|afternoon|evening)|thanks|thank\s+you|"
                r"thanku|ok(?:ay)?\s+thanks|bye|goodbye|see\s+you)\b")
_WEAK_COMPLAINT = re.compile(r"\b(?:issue|problem|trouble)\b", re.I)
_BANKING_NOUN = re.compile(r"\b(?:loan|account|card|payment|transfer|upi|neft|imps|atm|emi|money|amount|charge|"
                           r"debit|credit|cheque|app|netbanking|branch|interest|bank)\w*", re.I)

_DIGIT_WORDS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine".split())}
_DIGIT_WORD = re.compile(r"\b(?:" + "|".join(_DIGIT_WORDS) + r"|oh)\b", re.I)
_DIGIT_RUN = re.compile(r"(?<![\d])\+?\d[\d\s-]{8,30}\d(?![\d])")
_DOB = _rx(r"\bdate\s+of\s+birth\b", r"\bdob\b", r"\bborn\s+on\b", r"\bbirthday\b",
           r"\b\d{1,2}[/.-]\d{1,2}[/.-](?:\d{2}|" + _BIRTH_YEAR + r")\b",
           r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH + r",?\s+" + _BIRTH_YEAR + r"\b",
           r"\b" + _MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+" + _BIRTH_YEAR + r"\b")


def _identity_at(text: str) -> int | None:
    digits = _DIGIT_WORD.sub(lambda m: _DIGIT_WORDS.get(m.group(0).lower(), "0"), text)
    for m in _DIGIT_RUN.finditer(digits):
        n = re.sub(r"\D", "", m.group(0))
        if len(n) == 10 or (len(n) == 12 and n.startswith("91")):
            return m.start()
    m = _DOB.search(text)
    return m.start() if m else None


def rules_classify(text: str) -> IntentResult:
    text = text or ""
    found: dict[Intent, int] = {}
    for intent, pattern in _RULES.items():
        m = pattern.search(text)
        if m:
            found[intent] = m.start()
    if Intent.COMPLAINT not in found and (weak := _WEAK_COMPLAINT.search(text)) and _BANKING_NOUN.search(text):
        found[Intent.COMPLAINT] = weak.start()
    if (pos := _identity_at(text)) is not None:
        found[Intent.IDENTITY] = pos
    if not found and (greet := _CHITCHAT.search(text)) and len(text[greet.end():].split()) <= 3:  # "Hi, I have an issue with…" is not small talk
        return IntentResult([Intent.CHITCHAT], 0.7, IntentSource.RULES)
    if not found:
        return IntentResult([Intent.UNCLEAR], 0.3, IntentSource.RULES)
    return IntentResult(sorted(found, key=found.get), 0.6, IntentSource.RULES)


SYSTEM_PROMPT = """You label a bank customer's latest utterance with service intents.
Labels:
LOAN_APPLICATION: status or details of a loan application already made
REPAYMENT: EMI/instalment amount or due date, overdue, outstanding, repayment, foreclosure
ACCOUNT: bank account balance, transactions, account details
SERVICE_REQUEST: status of an existing ticket (e.g. SR-40102) or a request for a document or change: a statement, repayment schedule, NOC, certificate, address change (asking to be SENT a repayment schedule is SERVICE_REQUEST, not REPAYMENT)
PRODUCT_INFO: general product questions: rates, eligibility, documents, how to apply
COMPLAINT: a problem or grievance: failed transfer, wrong charge, money debited, poor service
INSURANCE: insurance policy, premium, cover or claim
IDENTITY: the caller gives their mobile number or date of birth
HUMAN_AGENT: asks for a human, agent or person
UNSUPPORTED: outside this bank's supported services or not permitted (weather, travel, stock tips, jokes, sending money to someone)
UNCLEAR: too vague to tell which service is meant, e.g. "an issue with the thing from last time" names no product or problem
CHITCHAT: greeting, thanks, goodbye, filler
The utterance may be in Kannada (Kannada script, or Kannada mixed with English words such as EMI, loan, statement); label it the same way, e.g. "ನನ್ನ ಮುಂದಿನ EMI ಯಾವಾಗ?" is REPAYMENT and "ನನಗೆ ಲೋನ್ ಸ್ಟೇಟ್‌ಮೆಂಟ್ ಬೇಕು" is SERVICE_REQUEST. Spoken digits in Kannada (ಒಂಬತ್ತು ಎಂಟು ...) giving a mobile number or date of birth are IDENTITY.
The utterance may also be in Hindi (Devanagari script, or Hindi mixed with English words); label it the same way, e.g. "मेरी अगली EMI कब है?" is REPAYMENT and "मुझे लोन स्टेटमेंट चाहिए" is SERVICE_REQUEST. Hindi digit words (नौ आठ सात ...) giving a mobile number or date of birth are IDENTITY.
Use the recent turns to resolve follow-ups like "and the vehicle one?". Give every label that applies, most important first.
Reply with JSON only: {"intents": ["LABEL", ...], "confidence": 0.0-1.0}"""

_HISTORY_TURNS = 4
_HISTORY_CHARS = 300


def _user_message(text: str, history_tail: list[dict]) -> str:
    lines = []
    for turn in (history_tail or [])[-_HISTORY_TURNS:]:
        role, content = turn.get("role"), turn.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            lines.append(f"{'customer' if role == 'user' else 'agent'}: {content.strip()[:_HISTORY_CHARS]}")
    recent = "Recent turns:\n" + "\n".join(lines) + "\n\n" if lines else ""
    return f"{recent}Latest customer utterance: {text}"


def _parse(content: str) -> IntentResult | None:
    data = json.loads(content)
    intents: list[Intent] = []
    for label in data.get("intents") or []:
        key = str(label).strip().upper()
        if key in Intent.__members__ and Intent(key) not in intents:
            intents.append(Intent(key))
    if not intents:
        return None
    try:
        confidence = min(max(float(data.get("confidence", 0.5)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.5
    return IntentResult(intents, confidence, IntentSource.LLM)


async def classify(text: str, history_tail: list[dict], *, api_key: str, model: str,
                   transport: httpx.AsyncBaseTransport | None = None, timeout: float = 1.5) -> IntentResult:
    """LLM labels for `text`; any failure, timeout, empty answer or missing key falls back to the rules."""
    if not api_key or not (text or "").strip():
        return rules_classify(text)
    body = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": _user_message(text, history_tail)}],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_completion_tokens": 400,
    }
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            resp = await asyncio.wait_for(
                client.post(f"{PROVIDERS['groq']}/chat/completions", json=body,
                            headers={"Authorization": f"Bearer {api_key}"}),
                timeout)
        resp.raise_for_status()
        result = _parse(resp.json()["choices"][0]["message"]["content"] or "")
        if result is not None:
            return result
        logger.info("intent classifier: LLM gave no known label, using rules")
    except httpx.HTTPStatusError as e:
        logger.warning(f"intent classifier: HTTP {e.response.status_code}, using rules")
    except Exception as e:
        logger.warning(f"intent classifier: {type(e).__name__}, using rules")
    return rules_classify(text)
