# Problem #05: CSM Voice Agent (requirements checklist)

A summary, in our own words, of the organisers' challenge pack (Level 1) for problem #05, plus the common rules. Use it as the source of truth for scope, seed data and test scenarios.

## Common rules
- **Level 1** (suggested 0–3 hours): a working end-to-end core journey.
- **Judging:** points for **observable behaviour**, not slides or unsupported AI claims. A prototype is not certified for regulatory compliance, so never claim it is.
- **Data:** synthetic or anonymised only. No production credentials, real customer data, external payments or live collection calls.
- **What the organisers provide:** schemas, sample data, hidden tests, sandbox credentials, the rubric and the policy rules. None has arrived yet; our seed data stands in until it does.
- **No AI resources are provided.** Teams use their own model keys. **Our rule:** never Anthropic; Groq first, then Gemini and Mistral.
- **Level 1 acceptance (from the organisers):** judges use **unseen utterances with accents and noise** and check the **correct intent**, the **ticket**, and a **refusal on unsupported requests**.
- **Example:** a caller asks about a service request, then asks an unsupported question. The agent captures the request and routes the unknown query.

## The problem
A bank's customers still phone in for routine things: loan application status, the next instalment, a statement, a failed transaction, a complaint. Answering means verifying identity, checking several systems, explaining the result and raising service requests. Fixed IVR menus are slow.

The agent must:
- understand intent, including several requests in one call;
- verify the customer before sharing anything personal;
- fetch real values from connected (simulated) systems;
- run permitted service workflows through approved APIs;
- keep a full record;
- escalate sensitive or unresolved matters to a human.

It needs a voice interface and an operational dashboard. The organisers judge live behaviour, not a prerecorded demo.

## Scenarios
1. **Loan application status:** verify, read the stage from the loan origination system, explain it plainly. Never say "approved" if it is awaiting document verification.
2. **Repayment and instalment:** next instalment amount and due date, outstanding balance, schedule, from the loan management system. Keep scheduled and overdue amounts separate. Never invent figures.
3. **Account and transaction:** balance, recent transaction, transaction status, after verification. For a pending or failed transaction, state the recorded status without guessing the cause.
4. **Service request creation and tracking:** for example a statement, a repayment schedule or an account document. Collect the details, create a ticket, give the reference. Report the status of an existing ticket.
5. **Complaint and escalation:** a failed transaction, incorrect charge or poor service. Capture it, classify it, create a record, give the reference. Escalate to a human when it is sensitive, urgent or beyond the agent's authority.
6. **Insurance policy and claim:** policy, premium due date, coverage status, claim status, from the insurance system. Never promise approval or coverage.
7. **Several requests in one call:** for example repayment, then a statement, then an existing complaint. Keep the same customer context and don't restart.
8. **Interruptions, ambiguity, incomplete input:** for example "No, I meant my vehicle loan, not my personal loan." Update the context and continue.
9. **Sensitive requests and failed verification:** another person's data or an unauthorised action. Enforce access, disclose nothing protected, escalate if needed.
10. **Languages:** at least one language at Level 1; more languages (Hindi, Arabic) later.

## Level 1 required capabilities
1. **Voice input and recognition:** mic or equivalent, natural phrasing. "When is my next EMI?", "How much do I need to pay next month?", "Tell me my next loan instalment" and "What's the due date for my personal loan?" all mean **repayment**. The **recognised transcript is shown**.
2. **Intent identification (minimum):**

   | Intent | Expected behaviour |
   |---|---|
   | Loan application enquiry | read and explain the application status |
   | Repayment enquiry | read the instalment amount and due date |
   | Account enquiry | read the permitted account information |
   | Service request enquiry | read an existing ticket's status |
   | General product enquiry | answer from an approved knowledge source |
   | Complaint or issue | identify the issue and start the service flow |

   If the request is unclear, **ask a clarifying question** rather than picking an unrelated service.
3. **Data integration (mock APIs are fine):** customer profiles; loan applications (reference, product, status); loan accounts (schedule, outstanding, instalments); bank accounts (balance, transactions); service requests (id, category, status); product information and FAQs. **Use actual stored values, never invented ones.**
4. **Basic verification** before account-specific information. General product questions need none. Loans, transactions, account details and personal service records need it.
5. **Natural spoken responses:** conversational and short, never raw API data, with the **text shown next to the audio**. For example: "Your personal loan application is currently under document verification. No additional action is recorded as required from you at this stage."
6. **Service interface showing:** recognised speech, identified intent, authentication status, retrieved service information, agent response, conversation history. The user can **start and end** a conversation and **inspect the information used** for each response.

**Expected submission:** a working voice customer-service app demonstrating speech recognition, intent identification, verification, financial information retrieval and spoken responses.
