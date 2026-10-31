# Verification Lab

The eight synthetic customers the bank simulator loads: what to say to verify as each of them, what the agent should then tell you, and the tests the desk must refuse. Nothing here is a real person. The interactive version is [verification-lab.html](verification-lab.html) (open it in a browser).

- Verify with the registered mobile number and date of birth.
- Three wrong attempts lock that customer for 15 minutes, across calls.
- A caller who fails for three different customers is blocked, and a security escalation is raised.
- Reset between runs: `curl -u ops:ops -X POST http://localhost:8090/v1/ops/reset`

Dates are relative to the simulator's start, as the seed stores them ("in 5 days").

## Customers

| Customer | Mobile | Date of birth | Set up for |
|---|---|---|---|
| Asha Verma (`CUST-1001`) | `98452 13076` | `1990-04-12` | Loan application in document verification |
| Rahul Iyer (`CUST-1002`) | `97314 62580` | `1985-11-03` | Two loans, an open statement request |
| Fatima Khan (`CUST-1003`) | `89523 04716` | `1992-07-21` | Vehicle loan with an overdue EMI, rejected address change |
| Arjun Nair (`CUST-1004`) | `74061 58293` | `1978-02-14` | A failed and a pending transfer, request awaiting info |
| Meera Pillai (`CUST-1005`) | `96204 87135` | `1988-09-30` | Health claim under review, lapsed motor policy, resolved request |
| Vikram Rao (`CUST-1006`) | `81935 62704` | `1995-12-05` | Home loan, open complaint |
| Sana Mirza (`CUST-1007`) | `75819 40362` | `1999-05-18` | Rejected application, low balance |
| David Fernandes (`CUST-1008`) | `93047 61852` | `1982-03-09` | Disputed ₹48,999 card payment |
| Karthik Menon (`CUST-1009`) | `93809 39280` | `1990-01-01` |  |

## Asha Verma

Personal loan application in document verification; no loan account yet, so no EMI schedule.

**Verify:** "My number is nine eight four five two, one three zero seven six, and I was born on the 12th April 1990."

| Say | Expect |
|---|---|
| "What's the status of my personal loan application?" | Document Verification; next step: None required from you. It must not say "approved" |
| "Please send me my loan statement." | A new SR- ticket, read back letter by letter and digit by digit |





## Rahul Iyer

Personal and vehicle loans (for the correction test), a savings account and request SR-40102.

**Verify:** "My number is nine seven three one four, six two five eight zero, and I was born on the 3rd November 1985."

| Say | Expect |
|---|---|
| "When is my next personal loan EMI?" | ₹12,450 due in 5 days |
| "When is my next vehicle loan EMI?" | ₹9,800 due in 12 days |
| "No, I meant my vehicle loan." | Switches to VL-31003 without verifying again |
| "What's the balance in my savings account?" | ₹85,400 in account ••• ••• 4012 |
| "What's the status of my request SR-40102?" | in progress: Account statement request for last 6 months. Progress: With the Account Services team. |
| "Please send me my loan statement." | A new SR- ticket, read back letter by letter and digit by digit |

| Loan | Type | Outstanding | Next EMI | Due | Overdue |
|---|---|---|---|---|---|
| `PL-31002` | Personal Loan | ₹2,80,000 | ₹12,450 | in 5 days | — |
| `VL-31003` | Vehicle Loan | ₹4,50,000 | ₹9,800 | in 12 days | — |

| Account | Type | Number | Balance |
|---|---|---|---|
| `ACC-20002` | savings | ••• ••• 4012 | ₹85,400 |



## Fatima Khan

An overdue instalment kept separate from the next one; her loan VL-31007 is the 'someone else's record' target. Address-change request SR-40103 was rejected (unreadable proof).

**Verify:** "My number is eight nine five two three, zero four seven one six, and I was born on the 21st July 1992."

| Say | Expect |
|---|---|
| "When is my next vehicle loan EMI?" | ₹9,800 due in 21 days; separately ₹9,800 overdue since 9 days ago |
| "What's the status of my request SR-40103?" | rejected: Change of registered address. Progress: Rejected: the address proof was unreadable. Please submit a clear copy. |
| "Please send me my loan statement." | A new SR- ticket, read back letter by letter and digit by digit |

| Loan | Type | Outstanding | Next EMI | Due | Overdue |
|---|---|---|---|---|---|
| `VL-31007` | Vehicle Loan | ₹3,20,000 | ₹9,800 | in 21 days | ₹9,800 |




## Arjun Nair

Transfer TXN-88213 failed with no recorded reason; TXN-88214 is pending. Request SR-40104 is waiting for the delivery address.

**Verify:** "My number is seven four zero six one, five eight two nine three, and I was born on the 14th February 1978."

| Say | Expect |
|---|---|
| "What's the balance in my savings account?" | ₹42,300 in account ••• ••• 8821 |
| "What happened to transaction TXN-88213?" | Recorded status failed; no guessed cause |
| "What happened to transaction TXN-88214?" | Recorded status pending |
| "What's the status of my request SR-40104?" | awaiting info: Interest certificate by post. Progress: Waiting for the customer to confirm the delivery address. |
| "Please send me my loan statement." | A new SR- ticket, read back letter by letter and digit by digit |


| Account | Type | Number | Balance |
|---|---|---|---|
| `ACC-20004` | savings | ••• ••• 8821 | ₹42,300 |

| Transaction | When | Description | Amount | Status |
|---|---|---|---|---|
| `TXN-88213` | 1 days ago | NEFT Transfer to Rajesh Sharma | −₹15,000 | failed |
| `TXN-88214` | today | UPI Payment to Swiggy | −₹2,300 | pending |


## Meera Pillai

Health policy in force with claim CLM-7001 under review; the motor policy has lapsed. Statement request SR-40105 was resolved.

**Verify:** "My number is nine six two zero four, eight seven one three five, and I was born on the 30th September 1988."

| Say | Expect |
|---|---|
| "What's the status of my request SR-40105?" | resolved: Account statement request for last 3 months. Progress: Statement sent to the registered email address. |
| "Is my Family Health Protect policy active?" | In Force (active); premium ₹14,500 due in 18 days |
| "Is my Comprehensive Motor Insurance policy active?" | Lapsed due to non-payment of renewal premium (lapsed); premium ₹8,200 due 45 days ago |
| "What's happening with my claim CLM-7001?" | under review; it must not promise approval |
| "Please send me my loan statement." | A new SR- ticket, read back letter by letter and digit by digit |




| Policy / claim | Product | Status | Amount | Due / filed |
|---|---|---|---|---|
| `HP-77001` | Family Health Protect | In Force | ₹14,500 | in 18 days |
| `MP-77002` | Comprehensive Motor Insurance | Lapsed due to non-payment of renewal premium | ₹8,200 | 45 days ago |
| `CLM-7001` | Claim on HP-77001 | under review | ₹65,000 | 4 days ago |

## Vikram Rao

Home loan and complaint CMP-50011 about an incorrect charge.

**Verify:** "My number is eight one nine three five, six two seven zero four, and I was born on the 5th December 1995."

| Say | Expect |
|---|---|
| "When is my next home loan EMI?" | ₹34,200 due in 15 days |
| "Any update on my complaint CMP-50011?" | open: Incorrect annual maintenance charge debited to home loan account |
| "Please send me my loan statement." | A new SR- ticket, read back letter by letter and digit by digit |

| Loan | Type | Outstanding | Next EMI | Due | Overdue |
|---|---|---|---|---|---|
| `HL-90182` | Home Loan | ₹35,00,000 | ₹34,200 | in 15 days | — |




## Sana Mirza

Loan application LA-24009 rejected; a current account with a low balance.

**Verify:** "My number is seven five eight one nine, four zero three six two, and I was born on the 18th May 1999."

| Say | Expect |
|---|---|
| "What's the status of my personal loan application?" | Application Rejected; next step: Application closed. You may reapply after 6 months.. It must not say "approved" |
| "What's the balance in my current account?" | ₹1,200 in account ••• ••• 1905 |
| "Please send me my loan statement." | A new SR- ticket, read back letter by letter and digit by digit |


| Account | Type | Number | Balance |
|---|---|---|---|
| `ACC-20007` | current | ••• ••• 1905 | ₹1,200 |



## David Fernandes

Card payment TXN-90011 he will say he didn't make: complaint plus escalation.

**Verify:** "My number is nine three zero four seven, six one eight five two, and I was born on the 9th March 1982."

| Say | Expect |
|---|---|
| "What's the balance in my savings account?" | ₹1,15,000 in account ••• ••• 9001 |
| "What happened to transaction TXN-90011?" | Recorded status posted |
| "I did not make this forty-eight thousand nine hundred ninety-nine rupee card payment." | Complaint (unauthorised transaction), CMP- reference, escalated to a person |
| "Please send me my loan statement." | A new SR- ticket, read back letter by letter and digit by digit |


| Account | Type | Number | Balance |
|---|---|---|---|
| `ACC-20008` | savings | ••• ••• 9001 | ₹1,15,000 |

| Transaction | When | Description | Amount | Status |
|---|---|---|---|---|
| `TXN-90011` | 1 days ago | POS Debit - Luxury Electronics Mumbai | −₹48,999 | posted |


## Karthik Menon



**Verify:** "My number is nine three eight zero nine, three nine two eight zero, and I was born on the 1st January 1990."

| Say | Expect |
|---|---|
| "Please send me my loan statement." | A new SR- ticket, read back letter by letter and digit by digit |





## Tests that must be refused

| Test | Steps | Expected |
|---|---|---|
| Wrong date of birth ×3 | Rahul's number 97314 62580 with three wrong dates of birth, then the right one (3rd November 1985) | Attempts left 2 → 1 → locked; the right date is refused for 15 minutes on any call; nothing personal shared |
| Someone else's record | Verify as Rahul, ask "What's due on my brother's loan VL-31007?" (Fatima's) | Refused by the simulator (NOT_YOUR_RECORD); no figures spoken |
| One caller, several customers | On one call, wrong dates of birth for 98452 13076, 89523 04716 and 81935 62704, then Meera's correct details | Caller blocked (CALLER_BLOCKED), even correct details fail; a SECURITY escalation on the Escalations tab |
| Personal question first | Ask "What's my account balance?" before verifying | Asks for mobile and date of birth first; no data returned |
| Unsupported request | Raise a statement request, then "Book me a flight to Dubai" or "Give me stock tips" | Polite refusal, a routed query (RQ-), the ticket kept |
| Asking for a person | "I want to talk to a person", then say it again | First: it asks what you need. Second: an ESC- escalation, call-back promise and helpline number |
| Product question | "What documents do I need for a vehicle loan?" without verifying | Answered from the approved FAQ; off-topic questions are routed |

_Generated by `scripts/build-verification-lab.py` from `backend/simulator/data/seed/` on 31 Oct 2026._
