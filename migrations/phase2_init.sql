-- Phase 2 migrations: tables for open-set classification and rule self-evolution.
-- All tables live in the antiblack schema.

-- 1. dynamic_rules: rules produced by slang→rule bridge (Stage 1 candidate keywords)
CREATE TABLE IF NOT EXISTS antiblack.dynamic_rules (
    rule_id           VARCHAR(64) PRIMARY KEY,
    slang_candidate_id VARCHAR(64),
    level1_label      VARCHAR(64) NOT NULL,
    level2_label      VARCHAR(64) NOT NULL,
    keywords          JSONB NOT NULL,             -- list of plain-text keywords (no regex)
    source            VARCHAR(32) NOT NULL DEFAULT 'llm_bridge',  -- 'llm_bridge' / 'manual'
    hit_count         INTEGER NOT NULL DEFAULT 0, -- lifetime rule hits
    correct_count     INTEGER NOT NULL DEFAULT 0, -- hits confirmed correct (manual or feedback)
    is_enabled        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    last_hit_at       TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dynamic_rules_enabled
    ON antiblack.dynamic_rules(is_enabled) WHERE is_enabled = TRUE;

-- 2. pending_category_proposals: candidate pool for new categories proposed by LLM
-- Embedding column is created as a regular float8[] for now; if pgvector is enabled later
-- a migration can ALTER it to vector(1024) and rebuild the index.
CREATE TABLE IF NOT EXISTS antiblack.pending_category_proposals (
    proposal_id        VARCHAR(64) PRIMARY KEY,
    cluster_id         VARCHAR(64) NOT NULL,        -- HDBSCAN cluster id (stringified)
    proposed_level1    VARCHAR(64) NOT NULL,
    proposed_level2    VARCHAR(64) NOT NULL,
    chain_of_thought   TEXT,
    llm_confidence     REAL NOT NULL,
    sample_texts       JSONB NOT NULL,              -- list of representative samples (centroid sampling)
    sample_size        INTEGER NOT NULL,           -- cluster size
    embedding          DOUBLE PRECISION[],          -- mean embedding of cluster (1024-d)
    status             VARCHAR(32) NOT NULL DEFAULT 'pending',  -- pending / approved / rejected / merged
    merged_into        VARCHAR(64),                -- if merged, target proposal_id
    review_comment     TEXT,
    reviewer           VARCHAR(64),
    created_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    reviewed_at        TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_pending_proposals_status
    ON antiblack.pending_category_proposals(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pending_proposals_cluster
    ON antiblack.pending_category_proposals(cluster_id);

-- 3. slang_evaluations: dedup cache for slang→rule bridge (avoid LLM re-evaluation)
CREATE TABLE IF NOT EXISTS antiblack.slang_evaluations (
    slang_candidate_id VARCHAR(64) PRIMARY KEY,
    eval_status        VARCHAR(32) NOT NULL,        -- accepted / rejected
    suggested_level1   VARCHAR(64),
    suggested_keywords JSONB,
    llm_confidence     REAL,
    eval_json          JSONB,                       -- raw LLM response
    created_at         TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 4. clue_label_snapshot table was created in scripts/normalize_clue_labels.py
-- Ensure it exists for completeness
CREATE TABLE IF NOT EXISTS antiblack.clues_label_snapshot (
    clue_id    VARCHAR(255) PRIMARY KEY,
    old_label  TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
