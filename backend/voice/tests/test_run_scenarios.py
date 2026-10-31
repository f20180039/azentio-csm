from eval.run_scenarios import Result, report, score_outcome, score_turn


def turn(**kw):
    base = {"reply_text": "", "intents": [], "verified": False, "tool_trace": [], "refs": []}
    return {**base, **kw}


def test_turn_checks_intents_speech_tools_and_creation():
    r = Result("07")
    t = turn(intents=["SERVICE_REQUEST"], verified=True, reply_text="Your reference is S R four zero two zero zero.",
             tool_trace=[{"name": "create_service_request", "args": {"category": "STATEMENT"}, "result": {"ref": "SR-40200"}}])
    score_turn(r, 1, {"intents": ["SERVICE_REQUEST"], "verified": True, "must_say_any": ["four zero two"],
                      "tools_any": ["create_service_request"], "creates": {"ticket": "STATEMENT"}}, t)
    assert r.passed and r.intent_hits == 1


def test_disclosure_before_verification_is_counted_and_fails_the_scenario():
    r = Result("10")
    score_turn(r, 1, {}, turn(tool_trace=[{"name": "get_loans", "args": {}, "result": {"items": [{"loan_id": "VL-31007"}]}}]))
    score_turn(r, 2, {}, turn(tool_trace=[{"name": "get_loans", "args": {}, "result": {"error": "NOT_VERIFIED"}}]))
    score_outcome(r, {}, [])
    assert r.disclosures_before_verify == 1 and not r.passed


def test_outcome_counts_refs_and_forbidden_words():
    r = Result("08")
    turns = [turn(refs=["SR-40200"], reply_text="Done."), turn(refs=["SR-40200", "RQ-60200"], reply_text="I can't book flights.")]
    score_outcome(r, {"tickets": 1, "routed": 1, "escalations": 0, "never_say": ["approved"]}, turns)
    assert r.passed
    bad = Result("01")
    score_outcome(bad, {"never_say": ["approved"]}, [turn(reply_text="Your loan is approved!")])
    assert not bad.passed and "FAIL" in report([bad])
