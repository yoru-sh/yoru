-- Migration: Supabase Performance Optimization Views
-- Description: Reduce query load by 80-90% through database views, materialized views, and RPC functions
-- Date: 2026-01-18
-- Author: SaaSForge Team

-- ===== UP MIGRATION =====

-- ============================================================================
-- 1. MATERIALIZED VIEW: user_subscription_details
-- Impact: GET /me/subscription: 5-13 queries → 1 query
-- ============================================================================

CREATE MATERIALIZED VIEW user_subscription_details AS
SELECT
    s.id AS subscription_id,
    s.user_id,
    s.status,
    s.start_date,
    s.end_date,
    s.created_at,
    s.updated_at,
    p.id AS plan_id,
    p.name AS plan_name,
    p.description AS plan_description,
    p.price,
    p.billing_period,
    s.promo_code_id,
    pc.code AS promo_code,
    -- Aggregated features (JSONB) - merges plan_features + user_grants
    COALESCE(
        jsonb_object_agg(
            f.key,
            COALESCE(ug.grant_value, pf.value)
        ) FILTER (WHERE f.key IS NOT NULL),
        '{}'::jsonb
    ) AS features
FROM subscriptions s
JOIN plans p ON s.plan_id = p.id
LEFT JOIN promo_codes pc ON s.promo_code_id = pc.id
LEFT JOIN plan_features pf ON pf.plan_id = p.id
LEFT JOIN features f ON pf.feature_id = f.id
LEFT JOIN (
    SELECT user_id, feature_id, value AS grant_value
    FROM user_grants
    WHERE expires_at IS NULL OR expires_at > NOW()
) ug ON ug.user_id = s.user_id AND ug.feature_id = f.id
WHERE s.status = 'active'
GROUP BY s.id, s.user_id, s.status, s.start_date, s.end_date,
         s.created_at, s.updated_at, p.id, p.name, p.description,
         p.price, p.billing_period, s.promo_code_id, pc.code;

-- Create unique index for fast user lookup
CREATE UNIQUE INDEX idx_user_subscription_details_user_id
    ON user_subscription_details(user_id);

-- Auto-refresh function for materialized view
CREATE OR REPLACE FUNCTION refresh_user_subscription_details()
RETURNS TRIGGER AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY user_subscription_details;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Triggers to auto-refresh materialized view on data changes
CREATE TRIGGER refresh_subscription_view
    AFTER INSERT OR UPDATE OR DELETE ON subscriptions
    FOR EACH STATEMENT
    EXECUTE FUNCTION refresh_user_subscription_details();

CREATE TRIGGER refresh_grants_view
    AFTER INSERT OR UPDATE OR DELETE ON user_grants
    FOR EACH STATEMENT
    EXECUTE FUNCTION refresh_user_subscription_details();

CREATE TRIGGER refresh_plan_features_view
    AFTER INSERT OR UPDATE OR DELETE ON plan_features
    FOR EACH STATEMENT
    EXECUTE FUNCTION refresh_user_subscription_details();

-- ============================================================================
-- 2. VIEW: user_profiles_with_email
-- Impact: GET /me: 2 queries → 1 query
-- ============================================================================

CREATE OR REPLACE VIEW user_profiles_with_email AS
SELECT
    p.id,
    p.name,
    p.role,
    p.avatar_url,
    p.created_at,
    p.updated_at,
    au.email,
    au.email_confirmed_at,
    au.phone,
    au.last_sign_in_at
FROM profiles p
JOIN auth.users au ON p.id = au.id;

-- ============================================================================
-- 3. VIEW: user_active_grants_enriched
-- Impact: GET /me/grants: 1+N queries → 1 query
-- ============================================================================

CREATE OR REPLACE VIEW user_active_grants_enriched AS
SELECT
    ug.id,
    ug.user_id,
    ug.feature_id,
    ug.value,
    ug.reason,
    ug.granted_by,
    ug.expires_at,
    ug.created_at,
    f.key AS feature_key,
    f.name AS feature_name,
    f.type AS feature_type,
    f.description AS feature_description
FROM user_grants ug
JOIN features f ON ug.feature_id = f.id
WHERE ug.expires_at IS NULL OR ug.expires_at > NOW();

-- Create index on filtered base table for performance
CREATE INDEX IF NOT EXISTS idx_user_grants_active
    ON user_grants(user_id)
    WHERE expires_at IS NULL OR expires_at > NOW();

-- ============================================================================
-- 4. VIEW: user_groups_with_counts
-- Impact: GET /me/groups: Member count queries eliminated
-- ============================================================================

CREATE OR REPLACE VIEW user_groups_with_counts AS
SELECT
    ug.id,
    ug.name,
    ug.description,
    ug.is_active,
    ug.created_by,
    ug.created_at,
    ug.updated_at,
    (SELECT COUNT(*) FROM user_group_members WHERE group_id = ug.id) AS member_count
FROM user_groups ug
WHERE ug.is_active = true;

-- Create composite index for group membership lookups
CREATE INDEX IF NOT EXISTS idx_group_members_composite
    ON user_group_members(user_id, group_id);

-- ============================================================================
-- 5. RPC FUNCTION: get_user_groups_with_details
-- Impact: GET /me/groups: 1+2N queries → 1 RPC call
-- ============================================================================

CREATE OR REPLACE FUNCTION get_user_groups_with_details(p_user_id UUID)
RETURNS TABLE(
    id UUID,
    name TEXT,
    description TEXT,
    is_active BOOLEAN,
    created_by UUID,
    created_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    member_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ug.id,
        ug.name,
        ug.description,
        ug.is_active,
        ug.created_by,
        ug.created_at,
        ug.updated_at,
        COUNT(ugm2.user_id) AS member_count
    FROM user_group_members ugm
    JOIN user_groups ug ON ugm.group_id = ug.id
    LEFT JOIN user_group_members ugm2 ON ugm2.group_id = ug.id
    WHERE ugm.user_id = p_user_id
      AND ug.is_active = true
    GROUP BY ug.id, ug.name, ug.description, ug.is_active,
             ug.created_by, ug.created_at, ug.updated_at;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Verify all views were created
DO $$
BEGIN
    -- Check regular views
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_schema = 'public' AND table_name = 'user_profiles_with_email'
    ) THEN
        RAISE EXCEPTION 'View user_profiles_with_email was not created';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_schema = 'public' AND table_name = 'user_active_grants_enriched'
    ) THEN
        RAISE EXCEPTION 'View user_active_grants_enriched was not created';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.views
        WHERE table_schema = 'public' AND table_name = 'user_groups_with_counts'
    ) THEN
        RAISE EXCEPTION 'View user_groups_with_counts was not created';
    END IF;

    -- Check materialized view
    IF NOT EXISTS (
        SELECT 1 FROM pg_matviews
        WHERE schemaname = 'public' AND matviewname = 'user_subscription_details'
    ) THEN
        RAISE EXCEPTION 'Materialized view user_subscription_details was not created';
    END IF;

    -- Check RPC function
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'public' AND p.proname = 'get_user_groups_with_details'
    ) THEN
        RAISE EXCEPTION 'Function get_user_groups_with_details was not created';
    END IF;

    RAISE NOTICE 'All views, materialized views, and functions created successfully!';
END $$;

-- ===== DOWN MIGRATION (ROLLBACK) =====
-- Uncomment the following lines to rollback this migration:

-- DROP TRIGGER IF EXISTS refresh_subscription_view ON subscriptions;
-- DROP TRIGGER IF EXISTS refresh_grants_view ON user_grants;
-- DROP TRIGGER IF EXISTS refresh_plan_features_view ON plan_features;
-- DROP FUNCTION IF EXISTS refresh_user_subscription_details();
-- DROP MATERIALIZED VIEW IF EXISTS user_subscription_details;
-- DROP VIEW IF EXISTS user_profiles_with_email;
-- DROP VIEW IF EXISTS user_active_grants_enriched;
-- DROP VIEW IF EXISTS user_groups_with_counts;
-- DROP FUNCTION IF EXISTS get_user_groups_with_details(UUID);
-- DROP INDEX IF EXISTS idx_user_grants_active;
-- DROP INDEX IF EXISTS idx_group_members_composite;
