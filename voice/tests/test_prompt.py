from app.prompt import system_prompt

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
