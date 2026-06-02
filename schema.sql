CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE claimants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name   TEXT NOT NULL,
    email       TEXT NOT NULL,
    phone       TEXT,
    national_id TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TYPE claim_status AS ENUM (
    'pending', 'processing', 'complete', 'error',
    'approved', 'rejected', 'escalated'
);

CREATE TABLE claims (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claimant_id      UUID NOT NULL REFERENCES claimants(id),
    status           claim_status NOT NULL DEFAULT 'pending',
    verdict          TEXT,
    drive_folder_id  TEXT,
    submitted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at      TIMESTAMPTZ,
    worker_notes     TEXT,
    worker_decision  TEXT,
    result_json      JSONB,
    documents_json   JSONB,
    error_log        JSONB
);

CREATE INDEX idx_claims_claimant  ON claims(claimant_id);
CREATE INDEX idx_claims_status    ON claims(status);
CREATE INDEX idx_claims_verdict   ON claims(verdict);

-- ALTER TABLE claims
--     DROP COLUMN IF EXISTS drive_folder_id,
--     ADD COLUMN IF NOT EXISTS storage_files_json JSONB;