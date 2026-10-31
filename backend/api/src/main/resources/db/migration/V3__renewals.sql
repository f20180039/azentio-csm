CREATE TABLE policies (
    id                 text PRIMARY KEY,
    holder_name        text          NOT NULL,
    date_of_birth      date          NOT NULL,
    mobile_last4       char(4)       NOT NULL,
    product            text          NOT NULL,
    sum_insured        numeric(12,0) NOT NULL,
    expires_on         date          NOT NULL,
    last_premium       numeric(12,0) NOT NULL,
    renewal_premium    numeric(12,0) NOT NULL,
    premium_breakdown  jsonb         NOT NULL DEFAULT '[]',
    addons             jsonb         NOT NULL DEFAULT '[]',
    claim_rejected_12m boolean       NOT NULL DEFAULT false,
    open_complaint     boolean       NOT NULL DEFAULT false,
    autodebit_failed   boolean       NOT NULL DEFAULT false,
    reminders_ignored  int           NOT NULL DEFAULT 0,
    do_not_call        boolean       NOT NULL DEFAULT false
);

CREATE TABLE calls (
    id                      uuid PRIMARY KEY REFERENCES cases (id),
    policy_id               text        NOT NULL REFERENCES policies (id),
    started_at              timestamptz NOT NULL DEFAULT now(),
    ended_at                timestamptz,
    identity_verified       boolean     NOT NULL DEFAULT false,
    verify_failures         int         NOT NULL DEFAULT 0,
    out_of_playbook_requests int        NOT NULL DEFAULT 0,
    must_handoff            boolean     NOT NULL DEFAULT false,
    outcome                 text,
    last_quote              jsonb,
    payment_link_sent       boolean     NOT NULL DEFAULT false,
    handoff_reason          text,
    callback_at             text,
    transcript              jsonb       NOT NULL DEFAULT '[]'
);
CREATE INDEX calls_policy_idx ON calls (policy_id);
