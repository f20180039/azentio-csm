# Problem 05, Level 2: Execute Service Requests, Manage Conversations and Escalate Issues

Source: `Hackathon_Challenge_Pack_Level1_Level2_8058.pdf` (HackCulture, 31 Oct 2026), section 5, pages 23–24. Copied verbatim; the 7 capabilities are headings.

Suggested time: 3 - 5.5 hours

Objective: Extend the voice assistant into an operational customer service agent that handles multiple requests, executes authorised workflows, maintains conversational context and creates service records.

## Required Capabilities

### 1. Multi-Turn Conversation Management

Build a mechanism that allows the voice agent to maintain context across multiple exchanges.

For example:

Customer: "When is my next personal loan instalment?"

Agent: "Your next instalment is due on 5 November."

Customer: "And how much is it?"

Agent: "The scheduled instalment amount is ₹12,500."

Customer: "Can you send me the repayment schedule?"

The agent should recognise that the customer is still referring to the same loan account. It should not require the customer to repeat the product and account details for every question unless verification or ambiguity requires it. The agent should also handle corrections, changes of topic and multiple eligible accounts.

### 2. Service Request Creation Through APIs

Enable the voice agent to execute supported customer service operations. For example, a customer may request a loan statement, repayment schedule or callback. The application should collect the required information, validate the request and call the appropriate service API.

The system must create a real record in the simulated CSM application or backend database. It should return a service request reference number and communicate it to the customer.

For example:

"Your repayment statement request has been registered successfully. Your service request number is SR-1042."

The agent must not claim that a request has been completed if the underlying API failed.

### 3. Service Request Status Tracking

Allow customers to enquire about previously registered service requests. The agent should retrieve the current ticket status, assigned department and available progress information. It should distinguish between requests that are open, in progress, resolved, rejected or awaiting additional information. If a request is unresolved, the agent may offer to register a follow-up or escalate the issue where permitted.

### 4. Complaint Registration and Classification

Build a mechanism to recognise complaints and distinguish them from general enquiries. The agent should capture the nature of the complaint, relevant account or transaction reference, customer description and urgency. It should create a complaint record with an appropriate category and priority.

For example, a failed transaction complaint should be classified differently from a general request for product information. The application should retain the customer's original statement and a structured summary of the complaint.

### 5. Human Agent Escalation

Introduce an escalation workflow for situations that cannot be safely or effectively resolved through automation.

Escalation scenarios should include:

- Repeated authentication failures.

- Customer requests outside the agent's permitted authority.

- Unresolved complaints.

- Suspected unauthorised account activity.

- Repeated misunderstanding of customer intent.

- Customer requests to speak with a human representative.

The agent should create an escalation record containing the customer reference, issue category, conversation summary, relevant service records and reason for escalation. The application may simulate transferring the interaction to a human agent through an agent queue.

### 6. Conversation Transcript and Interaction History

Maintain a structured record of each customer interaction.

The record should include the conversation identifier, customer reference, recognised intents, authentication events, API operations, service requests, agent responses and escalation decisions. Users should be able to inspect the transcript and supporting system records. If speech recognition produces an incorrect transcript, an authorised reviewer should be able to correct the record while preserving the original recognised text.

### 7. Customer Service Operations Dashboard

Develop a dashboard for customer service teams. The dashboard should display active and completed interactions, common customer intents, service requests created, complaints registered, escalations and unresolved cases.

Users should be able to open an interaction and inspect the complete conversation and associated service records. The dashboard should distinguish successfully completed service operations from failed or pending actions.

## Expected Submission

An integrated CSM Voice Agent demonstrating multi-turn conversations, service request creation, complaint registration, ticket tracking, human escalation, interaction history and operational dashboards.
