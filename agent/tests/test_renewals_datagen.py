from datetime import date

from datagen.renewals import build_policies, render_sql

TODAY = date(2026, 10, 29)


def sql(seed=7, count=40):
    return render_sql(build_policies(seed, count, TODAY))


def test_same_seed_same_sql():
    assert sql(7) == sql(7)


def test_demo_policy_present():
    out = sql()
    for needle in ["'HF-2291-0457'", "'Meera Iyer'", "'1980-03-14'", "18450", "15120", '"premium": 2100',
                   "'2026-11-03'"]:
        assert needle in out


def test_mix():
    rows = build_policies(7, 40, TODAY)
    assert len(rows) == 40
    assert len({r["id"] for r in rows}) == 40
    assert sum(r["open_complaint"] for r in rows) >= 3
    assert sum(r["do_not_call"] for r in rows) >= 2
    assert sum(0 <= (r["expires_on"] - TODAY).days <= 7 for r in rows) >= 8
    assert sum(r["renewal_premium"] > 1.15 * r["last_premium"] for r in rows) >= 8
    for r in rows:
        assert r["renewal_premium"] == r["last_premium"] + sum(b["amount"] for b in r["premium_breakdown"])


def test_fixed_demo_rows():
    by_name = {r["holder_name"]: r for r in build_policies(7, 40, TODAY)}
    meera = by_name["Meera Iyer"]
    assert meera["product"] == "Health family floater" and meera["reminders_ignored"] == 2
    assert meera["premium_breakdown"] == [{"label": "Age band 41–45 to 46–50", "amount": 2610},
                                          {"label": "Medical inflation", "amount": 720}]
    assert {"code": "OPD", "name": "Outpatient cover", "premium": 2100, "optional": True} in meera["addons"]
    arjun = by_name["Arjun Mehta"]
    assert arjun["open_complaint"] and arjun["claim_rejected_12m"] and arjun["expires_on"] == date(2026, 11, 7)
    sana = by_name["Sana Qureshi"]
    assert sana["renewal_premium"] == sana["last_premium"] and sana["expires_on"] == date(2026, 11, 1)
    kavya = by_name["Kavya Rao"]
    assert kavya["autodebit_failed"] and kavya["reminders_ignored"] == 2 and kavya["product"] == "Term life"
    rohan = by_name["Rohan Das"]
    assert round(rohan["renewal_premium"] / rohan["last_premium"], 2) == 1.09
    assert rohan["expires_on"] == date(2026, 11, 19) and rohan["reminders_ignored"] == 0
