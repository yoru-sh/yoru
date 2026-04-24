-- Migration: sessions.is_public — opt-in public share flag (GTM issue #79)
-- Description: Adds the is_public boolean used by GET /api/v1/public/sessions/{id}
--   to gate unauthenticated reads + by POST /sessions/{id}/share (and /revoke)
--   to toggle the gate. Default false — every existing session stays private.
-- Author: backend-dev
-- Date: 2026-04-24

-- Receipt v0 (SQLite, receipt.db) creates the `sessions` table from the
-- SQLModel in apps/api/api/routers/receipt/models.py via init_db()'s
-- create_all() — no SQL needed at boot once the column lives on the model.
-- This file documents the equivalent shape for the Supabase-managed table
-- so the same column lands on production.

-- Postgres / Supabase
ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT FALSE;

-- Index-only on the public slice so public-GET lookups stay cheap when the
-- table grows. Partial index — private rows don't pay the space/write cost.
CREATE INDEX IF NOT EXISTS idx_sessions_is_public_true
  ON sessions (id)
  WHERE is_public = TRUE;

-- SQLite (Receipt v0) — equivalent statement, in case create_all is skipped
-- on an existing receipt.db with the legacy schema.
-- ALTER TABLE sessions ADD COLUMN is_public BOOLEAN NOT NULL DEFAULT 0;
