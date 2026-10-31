#!/usr/bin/env python3
"""Builds the Verification Lab from the bank simulator's seed data: the synthetic customers, what to say to verify as each,
the answers to expect, and the tests the desk must refuse.

    python3 scripts/build-verification-lab.py

Writes docs/verification-lab.md (GitHub renders it; share the link) and docs/verification-lab.html (the same content as an
interactive page; open it in any browser, no server needed). Rerun after changing backend/simulator/data/seed/.
"""
import datetime
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "backend" / "simulator" / "data" / "seed"
TEMPLATE = ROOT / "docs" / "templates" / "verification-lab.html"
OUT_MD = ROOT / "docs" / "verification-lab.md"
OUT_HTML = ROOT / "docs" / "verification-lab.html"

NOTES = {  # what each customer is set up to demonstrate (matches the C2 seed table in docs/team/tasks-chirag.md)
    "CUST-1001": ("Loan application in document verification", "Personal loan application in document verification; no loan account yet, so no EMI schedule."),
    "CUST-1002": ("Two loans, an open statement request", "Personal and vehicle loans (for the correction test), a savings account and request SR-40102."),
    "CUST-1003": ("Vehicle loan with an overdue EMI, rejected address change", "An overdue instalment kept separate from the next one; her loan VL-31007 is the 'someone else's record' target. Address-change request SR-40103 was rejected (unreadable proof)."),
    "CUST-1004": ("A failed and a pending transfer, request awaiting info", "Transfer TXN-88213 failed with no recorded reason; TXN-88214 is pending. Request SR-40104 is waiting for the delivery address."),
    "CUST-1005": ("Health claim under review, lapsed motor policy, resolved request", "Health policy in force with claim CLM-7001 under review; the motor policy has lapsed. Statement request SR-40105 was resolved."),
    "CUST-1006": ("Home loan, open complaint", "Home loan and complaint CMP-50011 about an incorrect charge."),
    "CUST-1007": ("Rejected application, low balance", "Loan application LA-24009 rejected; a current account with a low balance."),
    "CUST-1008": ("Disputed ₹48,999 card payment", "Card payment TXN-90011 he will say he didn't make: complaint plus escalation."),
}
DIGITS = "zero one two three four five six seven eight nine".split()
MONTHS = "January February March April May June July August September October November December".split()


def load() -> dict:
    data = {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in sorted(SEED.glob("*.json")) if f.stem != "faq"}
    for c in data["customers"]:
        c["short"], c["scenario"] = NOTES.get(c["customer_ref"], ("", ""))
    return data


def inr(n) -> str:
    if n is None:
        return "—"
    s = str(int(n))
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return "₹" + ",".join(([head] if head else []) + groups + [tail]) if len(s) > 3 else "₹" + s


def spoken_mobile(m: str) -> str:
    return " ".join(DIGITS[int(c)] for c in m[:5]) + ", " + " ".join(DIGITS[int(c)] for c in m[5:])


def spoken_dob(iso: str) -> str:
    y, mo, d = (int(x) for x in iso.split("-"))
    suffix = "th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
    return f"{d}{suffix} {MONTHS[mo - 1]} {y}"


def days(n: int) -> str:
    return "today" if n == 0 else (f"in {n} days" if n > 0 else f"{-n} days ago")


def mine(data: dict, key: str, ref: str) -> list[dict]:
    return [r for r in data.get(key, []) if r["customer_ref"] == ref]


def table(head: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    out += ["| " + " | ".join(str(c).replace("|", "/") for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def markdown(data: dict, generated: str) -> str:
    md = [
        "# Verification Lab",
        "",
        "The eight synthetic customers the bank simulator loads: what to say to verify as each of them, what the agent should "
        "then tell you, and the tests the desk must refuse. Nothing here is a real person. The interactive version is "
        "[verification-lab.html](verification-lab.html) (open it in a browser).",
        "",
        "- Verify with the registered mobile number and date of birth.",
        "- Three wrong attempts lock that customer for 15 minutes, across calls.",
        "- A caller who fails for three different customers is blocked, and a security escalation is raised.",
        "- Reset between runs: `curl -u ops:ops -X POST http://localhost:8090/v1/ops/reset`",
        "",
        "Dates are relative to the simulator's start, as the seed stores them (\"in 5 days\").",
        "",
        "## Customers",
        "",
        table(["Customer", "Mobile", "Date of birth", "Set up for"],
              [[f"{c['first_name']} {c['last_name']} (`{c['customer_ref']}`)", f"`{c['mobile'][:5]} {c['mobile'][5:]}`", f"`{c['dob']}`", c["short"]]
               for c in data["customers"]]),
    ]
    for c in data["customers"]:
        ref = c["customer_ref"]
        apps, loans, accts, txns = (mine(data, k, ref) for k in ("applications", "loans", "accounts", "transactions"))
        tix, cmps, pols, clms = (mine(data, k, ref) for k in ("tickets", "complaints", "policies", "claims"))
        md += [f"## {c['first_name']} {c['last_name']}", "", c["scenario"], "",
               f"**Verify:** \"My number is {spoken_mobile(c['mobile'])}, and I was born on the {spoken_dob(c['dob'])}.\"", ""]
        tries = []
        for a in apps:
            tries.append((f"What's the status of my {a['product'].lower()} application?", f"{a['stage_label']}; next step: {a['next_step']}"
                          + ("" if a["stage"] in ("SANCTIONED", "DISBURSED") else ". It must not say \"approved\"")))
        for l in loans:
            over = f"; separately {inr(l['overdue']['amount'])} overdue since {days(-l['overdue']['since_days_ago'])}" if l.get("overdue") else ""
            tries.append((f"When is my next {l['product_type']} loan EMI?", f"{inr(l['next_instalment']['amount'])} due {days(l['next_instalment']['due_in_days'])}{over}"))
        if len(loans) > 1:
            tries.append((f"No, I meant my {loans[1]['product_type']} loan.", f"Switches to {loans[1]['loan_id']} without verifying again"))
        for a in accts:
            tries.append((f"What's the balance in my {a['type'].lower()} account?", f"{inr(a['balance'])} in account {a['masked_number']}"))
        for t in txns:
            tries.append((f"What happened to transaction {t['ref']}?", f"Recorded status {t['status'].lower()}" + ("; no guessed cause" if t["status"] == "FAILED" else "")))
        for t in tix:
            tries.append((f"What's the status of my request {t['ref']}?",
                          f"{t['status'].replace('_', ' ').lower()}: {t['summary']}. Progress: {t['progress']}"))
        for k in cmps:
            tries.append((f"Any update on my complaint {k['ref']}?", f"{k['status'].lower()}: {k['description']}"))
        for p in pols:
            tries.append((f"Is my {p['product']} policy active?", f"{p['coverage_status']} ({p['status'].lower()}); premium {inr(p['premium'])} due {days(p['due_in_days'])}"))
        for k in clms:
            tries.append((f"What's happening with my claim {k['claim_no']}?", f"{k['status'].replace('_', ' ').lower()}; it must not promise approval"))
        if ref == "CUST-1008":
            tries.append(("I did not make this forty-eight thousand nine hundred ninety-nine rupee card payment.", "Complaint (unauthorised transaction), CMP- reference, escalated to a person"))
        tries.append(("Please send me my loan statement.", "A new SR- ticket, read back letter by letter and digit by digit"))
        md += [table(["Say", "Expect"], [[f"\"{s}\"", e] for s, e in tries])]
        md += [table(["Loan", "Type", "Outstanding", "Next EMI", "Due", "Overdue"],
                     [[f"`{l['loan_id']}`", l["product"], inr(l["outstanding_principal"]), inr(l["next_instalment"]["amount"]),
                       days(l["next_instalment"]["due_in_days"]), inr(l["overdue"]["amount"]) if l.get("overdue") else "—"] for l in loans])]
        md += [table(["Account", "Type", "Number", "Balance"], [[f"`{a['account_id']}`", a["type"].lower(), a["masked_number"], inr(a["balance"])] for a in accts])]
        md += [table(["Transaction", "When", "Description", "Amount", "Status"],
                     [[f"`{t['ref']}`", days(-t["days_ago"]), t["description"], ("−" if t["direction"] == "DEBIT" else "+") + inr(t["amount"]), t["status"].lower()] for t in txns])]
        md += [table(["Policy / claim", "Product", "Status", "Amount", "Due / filed"],
                     [[f"`{p['policy_no']}`", p["product"], p["coverage_status"], inr(p["premium"]), days(p["due_in_days"])] for p in pols]
                     + [[f"`{k['claim_no']}`", f"Claim on {k['policy_no']}", k["status"].replace("_", " ").lower(), inr(k["amount_claimed"]), days(-k["submitted_days_ago"])] for k in clms])]
    md += [
        "## Tests that must be refused",
        "",
        table(["Test", "Steps", "Expected"], [
            ["Wrong date of birth ×3", "Rahul's number 98765 00002 with three wrong dates of birth, then the right one (3rd November 1985)",
             "Attempts left 2 → 1 → locked; the right date is refused for 15 minutes on any call; nothing personal shared"],
            ["Someone else's record", "Verify as Rahul, ask \"What's due on my brother's loan VL-31007?\" (Fatima's)", "Refused by the simulator (NOT_YOUR_RECORD); no figures spoken"],
            ["One caller, several customers", "On one call, wrong dates of birth for 98765 00001, 00003 and 00006, then Meera's correct details",
             "Caller blocked (CALLER_BLOCKED), even correct details fail; a SECURITY escalation on the Escalations tab"],
            ["Personal question first", "Ask \"What's my account balance?\" before verifying", "Asks for mobile and date of birth first; no data returned"],
            ["Unsupported request", "Raise a statement request, then \"Book me a flight to Dubai\" or \"Give me stock tips\"", "Polite refusal, a routed query (RQ-), the ticket kept"],
            ["Asking for a person", "\"I want to talk to a person\", then say it again", "First: it asks what you need. Second: an ESC- escalation, call-back promise and helpline number"],
            ["Product question", "\"What documents do I need for a vehicle loan?\" without verifying", "Answered from the approved FAQ; off-topic questions are routed"],
        ]),
        f"_Generated by `scripts/build-verification-lab.py` from `backend/simulator/data/seed/` on {generated}._",
        "",
    ]
    return "\n".join(md)


def html(data: dict, generated: str) -> str:
    body = TEMPLATE.read_text(encoding="utf-8").replace('<meta name="claude:viewport-fit-sides" content="cover">\n', "")
    body = body.replace("__DATA__", json.dumps(data, ensure_ascii=False)).replace("__GENERATED__", generated)
    title_end = body.index("</title>") + len("</title>")
    head, rest = body[:title_end], body[title_end:]
    style_end = rest.index("</style>") + len("</style>")
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            f"{head}{rest[:style_end]}\n</head>\n<body>\n{rest[style_end:]}\n</body>\n</html>\n")


def main() -> None:
    data = load()
    generated = datetime.date.today().strftime("%d %b %Y")
    OUT_MD.write_text(markdown(data, generated), encoding="utf-8")
    OUT_HTML.write_text(html(data, generated), encoding="utf-8")
    print(f"wrote {OUT_MD.relative_to(ROOT)} and {OUT_HTML.relative_to(ROOT)} ({len(data['customers'])} customers)")


if __name__ == "__main__":
    main()
