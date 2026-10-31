from app.prompt import system_prompt
from app.support_prompt import support_prompt
from app.vocab import SpeechLanguage

GREETING = "Hello Asha Rao, this is the Renewal Desk calling about your policy."


def test_greeting_and_rules_present():
    p = system_prompt(GREETING)
    assert GREETING in p
    assert "Never state any policy detail until verify_identity returns verified" in p
    assert ("Only offer what list_allowed_options returns; if a tool returns an error, "
            "say so plainly and do not promise anything") in p
    assert ("If any tool returns mustHandoff true, or the customer asks for a person, mentions a death, "
            "illness in distress or a complaint, call handoff_to_human") in p
    assert "Reply in one or two short spoken sentences, no lists, no markdown, say amounts in words" in p


def test_tool_led_discounts_consent_and_spoken_amounts():
    p = system_prompt(GREETING)
    assert ("When the customer asks for a discount or price cut, call quote_renewal with the discount_percent "
            "they asked for and relay the result; never refuse a discount yourself") in p
    assert "Only call send_payment_link after the customer has clearly agreed to one specific quote you read out" in p
    assert "Say amounts exactly as given in the spoken fields" in p


def test_dob_is_converted_by_the_agent():
    p = system_prompt(GREETING)
    assert ("Call verify_identity only with a date of birth the customer has actually said; convert it to "
            "YYYY-MM-DD yourself and never ask the customer for a format. "
            "If they have not said it yet, just ask for it without calling any tool") in p


def test_discount_asked_again_still_goes_to_the_tool():
    assert ("Do this every time they ask, even if a discount was already refused, and never reuse an earlier result in its place. "
            "A repeated request is a new quote_renewal call with the same discount_percent; "
            "the system alone decides when to stop and hand off") in system_prompt(GREETING)


def test_unnamed_discount_is_checked_with_the_tool():
    assert ("If the customer asks for a discount without naming a figure, call quote_renewal with "
            "discount_percent 1 to check whether any discount is allowed, then relay the result") in system_prompt(GREETING)


def test_options_only_on_objection():
    assert ("After verify_identity succeeds, call get_policy only; call list_allowed_options only when "
            "the customer objects to the price or asks for options") in system_prompt(GREETING)


def test_no_discounted_amount_without_a_successful_quote():
    assert "Never say an amount is discounted unless quote_renewal returned it without an error" in system_prompt(GREETING)


def test_prompt_asks_for_written_references_and_amounts():
    # X1: the transcript keeps the written form; the voice spells references out at TTS time (app.spoken.speakable)
    for p in (support_prompt(), support_prompt(languages=(SpeechLanguage.ENGLISH, SpeechLanguage.KANNADA, SpeechLanguage.HINDI))):
        assert "Write references exactly as the tool returns them (e.g. SR-40200)" in p
        assert "amounts with the rupee sign and digits (e.g. ₹12,450)" in p
        assert "Never spell references or numbers out in words" in p
        assert "letter by letter" not in p and "*_spoken" not in p and "four zero two zero zero" not in p
        assert "no raw codes" not in p  # STYLE must not contradict the written-reference rule
