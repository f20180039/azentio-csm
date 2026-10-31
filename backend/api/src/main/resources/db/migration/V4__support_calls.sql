-- Support calls share the calls table with renewal calls; kind tells them apart.
ALTER TABLE calls ALTER COLUMN policy_id DROP NOT NULL;

ALTER TABLE calls ADD COLUMN kind text NOT NULL DEFAULT 'RENEWAL'
    CONSTRAINT calls_kind_check CHECK (kind IN ('RENEWAL', 'SUPPORT'));

ALTER TABLE calls ADD COLUMN channel text
    CONSTRAINT calls_channel_check CHECK (channel IN ('VOICE', 'SIM_AUDIO', 'TEXT'));

-- outcome already exists with the renewal vocabulary (HANDED_OFF, ...), so this list binds SUPPORT rows only.
ALTER TABLE calls ADD CONSTRAINT calls_support_outcome_check
    CHECK (kind <> 'SUPPORT' OR outcome IS NULL
           OR outcome IN ('RESOLVED', 'TICKET_CREATED', 'COMPLAINT_REGISTERED', 'ROUTED', 'ESCALATED', 'ABANDONED'));

ALTER TABLE calls ADD CONSTRAINT calls_renewal_policy_check CHECK (kind <> 'RENEWAL' OR policy_id IS NOT NULL);

CREATE INDEX calls_kind_started_idx ON calls (kind, started_at DESC);
