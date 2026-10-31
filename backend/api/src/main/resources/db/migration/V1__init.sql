CREATE TABLE cases (
    id               uuid PRIMARY KEY,
    case_type        text        NOT NULL,
    title            text        NOT NULL,
    status           text        NOT NULL CHECK (status IN ('RECEIVED', 'PROCESSING', 'NEEDS_REVIEW', 'AUTO_CLEARED',
                                                            'ESCALATED', 'APPROVED', 'REJECTED', 'FAILED')),
    risk_score       numeric(4, 3),
    amount_at_risk   numeric(14, 2),
    pipeline_version text        NOT NULL,
    created_by       text        NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX cases_queue_idx ON cases (status, risk_score DESC, amount_at_risk DESC);

CREATE TABLE documents (
    id           uuid PRIMARY KEY,
    case_id      uuid        NOT NULL REFERENCES cases (id),
    filename     text        NOT NULL,
    mime_type    text,
    sha256       char(64)    NOT NULL,
    size_bytes   bigint      NOT NULL,
    storage_path text        NOT NULL,
    page_count   int,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX documents_sha256_idx ON documents (sha256);
CREATE INDEX documents_case_idx ON documents (case_id);

CREATE TABLE extractions (
    id             uuid PRIMARY KEY,
    document_id    uuid        NOT NULL REFERENCES documents (id),
    payload        jsonb       NOT NULL,
    model_provider text,
    model_name     text,
    prompt_version text,
    input_tokens   int,
    output_tokens  int,
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX extractions_document_idx ON extractions (document_id, created_at DESC);

CREATE TABLE findings (
    id              uuid PRIMARY KEY,
    case_id         uuid        NOT NULL REFERENCES cases (id),
    rule_id         text        NOT NULL,
    title           text        NOT NULL,
    detail          text,
    severity        text        NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH')),
    weight          numeric(5, 3) NOT NULL,
    amount          numeric(14, 2),
    source          text        NOT NULL CHECK (source IN ('RULE', 'MODEL', 'LLM', 'SECURITY')),
    evidence        jsonb       NOT NULL DEFAULT '[]'::jsonb,
    llm_note        text,
    verified        boolean,
    status          text        NOT NULL CHECK (status IN ('OPEN', 'ACCEPTED', 'DISMISSED', 'EDITED')),
    decided_by      text,
    decision_reason text,
    decided_at      timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX findings_case_idx ON findings (case_id);

CREATE TABLE jobs (
    id              uuid PRIMARY KEY,
    case_id         uuid        NOT NULL REFERENCES cases (id),
    kind            text        NOT NULL,
    status          text        NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'RETRY', 'DONE', 'FAILED')),
    attempts        int         NOT NULL DEFAULT 0,
    run_after       timestamptz NOT NULL DEFAULT now(),
    last_error      text,
    idempotency_key text UNIQUE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_claim_idx ON jobs (status, run_after);

CREATE TABLE audit_events (
    id         bigserial PRIMARY KEY,
    case_id    uuid,
    actor      text        NOT NULL,
    action     text        NOT NULL,
    payload    jsonb       NOT NULL,
    prev_hash  char(64)    NOT NULL,
    hash       char(64)    NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE INDEX audit_events_case_idx ON audit_events (case_id, id);

CREATE FUNCTION audit_events_append_only() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only (% blocked)', TG_OP;
END
$$;

CREATE TRIGGER audit_events_no_mutation
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();

CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_events_append_only();
