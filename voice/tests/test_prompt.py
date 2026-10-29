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
