-- Topic facts that arrive with the upload (policy number, declared income, deadline). Rules read them; peers match on them.
ALTER TABLE cases ADD COLUMN attributes jsonb NOT NULL DEFAULT '{}';
CREATE INDEX cases_attributes_idx ON cases USING gin (attributes jsonb_path_ops);
CREATE INDEX cases_type_created_idx ON cases (case_type, created_at DESC);
