from conftest import RAHUL, session_for, verify

WRONG_DOB = "2000-01-01"


def test_correct_details_give_a_session(client):
    res = verify(client, "CUST-1002")
    assert res.status_code == 200
    body = res.json()
    assert body["session"]
    assert body["expires_in"] == 900
    assert body["customer"] == {"customer_ref": "CUST-1002", "first_name": "Rahul"}


def test_mobile_is_normalised(client):
    for mobile in ("+919876500002", "09876500002", "+91 98765 00002"):
        res = client.post("/v1/verify", json={"mobile": mobile, "dob": RAHUL["dob"], "call_id": "c1"})
        assert res.status_code == 200, mobile


def test_wrong_dob_counts_down_then_locks_for_15_minutes(client, clock):
    first = verify(client, "CUST-1002", WRONG_DOB, call_id="c1")
    assert first.status_code == 401
    assert first.json()["error"] == "VERIFICATION_FAILED"
    assert first.json()["attempts_left"] == 2
    assert verify(client, "CUST-1002", WRONG_DOB, call_id="c1").json()["attempts_left"] == 1

    third = verify(client, "CUST-1002", WRONG_DOB, call_id="c1")
    assert third.status_code == 423
    assert third.json()["error"] == "LOCKED"

    # the lock is per customer, across calls
    clock.advance(minutes=14, seconds=59)
    later = verify(client, "CUST-1002", call_id="another-call")
    assert later.status_code == 423
    assert later.json()["error"] == "LOCKED"

    clock.advance(seconds=2)
    assert verify(client, "CUST-1002", call_id="another-call").status_code == 200


def test_lock_does_not_touch_other_customers(client):
    for _ in range(3):
        verify(client, "CUST-1002", WRONG_DOB, call_id="c1", caller_ref="+919000000001")
    assert verify(client, "CUST-1003", call_id="c2", caller_ref="+919000000002").status_code == 200


def test_success_clears_the_failure_count(client):
    verify(client, "CUST-1002", WRONG_DOB, call_id="c1")
    verify(client, "CUST-1002", WRONG_DOB, call_id="c1")
    assert verify(client, "CUST-1002", call_id="c1").status_code == 200
    assert verify(client, "CUST-1002", WRONG_DOB, call_id="c1").json()["attempts_left"] == 2


def test_personal_endpoint_without_session_is_not_verified(client):
    res = client.get("/v1/lms/loans")
    assert res.status_code == 401
    assert res.json()["error"] == "NOT_VERIFIED"
    assert client.get("/v1/lms/loans", headers={"X-Customer-Session": "bogus"}).json()["error"] == "NOT_VERIFIED"


def test_expired_session_is_not_verified(client, clock):
    headers = session_for(client, "CUST-1002")
    clock.advance(seconds=899)
    assert client.get("/v1/lms/loans", headers=headers).status_code == 200
    clock.advance(seconds=2)
    res = client.get("/v1/lms/loans", headers=headers)
    assert res.status_code == 401
    assert res.json()["error"] == "NOT_VERIFIED"


def test_another_customers_schedule_is_not_your_record(client):
    headers = session_for(client, "CUST-1002")
    res = client.get("/v1/lms/loans/VL-31007/schedule", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"] == "NOT_YOUR_RECORD"
    assert "items" not in res.json()


def test_second_verify_on_same_call_replaces_session(client):
    first = verify(client, "CUST-1002", call_id="same-call").json()["session"]
    second = verify(client, "CUST-1003", call_id="same-call").json()["session"]
    assert client.get("/v1/lms/loans", headers={"X-Customer-Session": first}).status_code == 401
    loans = client.get("/v1/lms/loans", headers={"X-Customer-Session": second}).json()["items"]
    assert [l["loan_id"] for l in loans] == ["VL-31007"]


def test_every_attempt_is_recorded_with_its_call_id(client, store):
    verify(client, "CUST-1002", WRONG_DOB, call_id="call-a")
    verify(client, "CUST-1002", call_id="call-b")
    with store._get_connection() as con:
        rows = con.execute("SELECT call_id, outcome, customer_ref FROM verification_attempts ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [("call-a", "FAILED", "CUST-1002"), ("call-b", "SUCCESS", "CUST-1002")]


# --- per-caller brute-force protection -------------------------------------------------------------

CALLER = "+919811100000"


def test_wrong_dob_for_three_customers_blocks_the_caller(client, store):
    assert verify(client, "CUST-1001", WRONG_DOB, call_id="bf-1", caller_ref=CALLER).status_code == 401
    assert verify(client, "CUST-1002", WRONG_DOB, call_id="bf-1", caller_ref=CALLER).status_code == 401
    third = verify(client, "CUST-1003", WRONG_DOB, call_id="bf-1", caller_ref=CALLER)
    assert third.status_code == 423
    assert third.json()["error"] == "CALLER_BLOCKED"

    # a correct verify for a fresh customer from the same caller (even on a new call) is refused
    fresh = verify(client, "CUST-1004", call_id="bf-2", caller_ref=CALLER)
    assert fresh.status_code == 423
    assert fresh.json()["error"] == "CALLER_BLOCKED"

    # a different caller is unaffected
    assert verify(client, "CUST-1004", call_id="other", caller_ref="+919822200000").status_code == 200

    esc = store.list_records("escalation")
    security = [e for e in esc if e["category"] == "SECURITY"]
    assert len(security) == 1
    assert security[0]["summary"].startswith("Repeated failed verification across 3 customers")
    assert security[0]["call_id"] == "bf-1"
    assert security[0]["ref"].startswith("ESC-")


def test_call_id_is_the_caller_key_when_no_caller_ref(client):
    for ref in ("CUST-1001", "CUST-1002", "CUST-1003"):
        verify(client, ref, WRONG_DOB, call_id="anon-call")
    assert verify(client, "CUST-1004", call_id="anon-call").json()["error"] == "CALLER_BLOCKED"
    assert verify(client, "CUST-1004", call_id="new-call").status_code == 200


def test_six_failures_in_total_block_the_caller(client):
    for ref in ("CUST-1001", "CUST-1002"):
        for _ in range(2):
            assert verify(client, ref, WRONG_DOB, call_id="c", caller_ref=CALLER).status_code == 401
    # unknown mobile numbers count as targets too, but keep to two targets here: retry the first two after a success
    assert verify(client, "CUST-1001", call_id="c", caller_ref=CALLER).status_code == 200
    assert verify(client, "CUST-1001", WRONG_DOB, call_id="c", caller_ref=CALLER).status_code == 401
    sixth = verify(client, "CUST-1001", WRONG_DOB, call_id="c", caller_ref=CALLER)
    assert sixth.json()["error"] == "CALLER_BLOCKED"


def test_caller_window_is_thirty_minutes(client, clock):
    verify(client, "CUST-1001", WRONG_DOB, call_id="c", caller_ref=CALLER)
    verify(client, "CUST-1002", WRONG_DOB, call_id="c", caller_ref=CALLER)
    clock.advance(minutes=31)
    assert verify(client, "CUST-1003", WRONG_DOB, call_id="c", caller_ref=CALLER).status_code == 401
