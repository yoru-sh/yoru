-- Migration: welcome_email_sent_at on users (wave-54 Hour-0)
-- Description: Adds the dedupe column used by POST /api/v1/auth/welcome-email
--   to ensure each user receives the install-snippet welcome email at most once.
-- Author: backend-dev
-- Date: 2026-04-21

-- Receipt v0 (SQLite, receipt.db) creates the `users` table from the
-- SQLModel in apps/api/api/routers/receipt/models.py via init_db()'s
-- create_all() — no SQL needed at boot. This file documents the equivalent
-- shape for the Supabase auth.users table so the same dedupe column lands
-- on the production identity store when activation goes live.

-- Postgres / Supabase
ALTER TABLE auth.users
  ADD COLUMN IF NOT EXISTS welcome_email_sent_at TIMESTAMPTZ;

-- SQLite (Receipt v0) — equivalent statement, in case create_all is
-- skipped on an existing receipt.db with the legacy schema.
-- ALTER TABLE users ADD COLUMN welcome_email_sent_at TIMESTAMP;
