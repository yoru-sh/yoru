-- Migration: Add rate_limit_per_minute feature
-- Description: Adds dynamic rate limiting feature to Supabase feature system
-- Date: 2026-01-17
-- Status: EXECUTED via Supabase MCP

-- 1. Add rate_limit_per_minute feature to features table
DO $$
DECLARE
    feature_id_var uuid;
    starter_plan_id uuid;
    pro_plan_id uuid;
BEGIN
    -- Insert feature
    INSERT INTO features (key, name, description, type, default_value)
    VALUES (
        'rate_limit_per_minute',
        'Rate Limit (requests/minute)',
        'Maximum number of API requests allowed per minute',
        'quota',
        '{"limit": 100}'::jsonb
    )
    ON CONFLICT (key) DO UPDATE
    SET
        name = EXCLUDED.name,
        description = EXCLUDED.description,
        type = EXCLUDED.type,
        default_value = EXCLUDED.default_value
    RETURNING id INTO feature_id_var;

    RAISE NOTICE 'Feature created/updated with ID: %', feature_id_var;

    -- Get plan IDs
    SELECT id INTO starter_plan_id FROM plans WHERE name = 'Starter' LIMIT 1;
    SELECT id INTO pro_plan_id FROM plans WHERE name = 'Professional' LIMIT 1;

    IF starter_plan_id IS NULL OR pro_plan_id IS NULL THEN
        RAISE EXCEPTION 'Required plans (Starter/Professional) not found';
    END IF;

    -- 2. Add plan features for Starter plan (100 req/min)
    INSERT INTO plan_features (plan_id, feature_id, value)
    VALUES (starter_plan_id, feature_id_var, '{"limit": 100}'::jsonb)
    ON CONFLICT (plan_id, feature_id) DO UPDATE
    SET value = EXCLUDED.value;

    RAISE NOTICE 'Starter plan limit: 100 req/min';

    -- 3. Add plan features for Professional plan (1000 req/min)
    INSERT INTO plan_features (plan_id, feature_id, value)
    VALUES (pro_plan_id, feature_id_var, '{"limit": 1000}'::jsonb)
    ON CONFLICT (plan_id, feature_id) DO UPDATE
    SET value = EXCLUDED.value;

    RAISE NOTICE 'Professional plan limit: 1000 req/min';

    RAISE NOTICE 'Rate limiting feature setup complete';
END $$;

-- Notes:
-- - Feature type is 'quota' (numeric limit)
-- - Value format: {"limit": <number>} (jsonb)
-- - Default is 100 req/min if no plan or override
-- - Can be overridden per-user via user_grants table
-- - Can be set per-group via user_group_features table
--
-- Hierarchical resolution (same as RBAC):
-- 1. user_grants (highest priority - admin overrides)
-- 2. user_group_features (via group membership)
-- 3. plan_features (via active subscription)
-- 4. default_value (lowest priority - fallback)
--
-- Example: Grant user higher limit
-- INSERT INTO user_grants (user_id, feature_id, value, granted_by)
-- VALUES (
--     'user-uuid-here',
--     (SELECT id FROM features WHERE key = 'rate_limit_per_minute'),
--     '{"limit": 5000}'::jsonb,
--     'admin-uuid-here'
-- );
