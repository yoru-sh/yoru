-- ============================================================================
-- Route Rules Schema Migration (Phase C — CLI multi-workspace routing)
-- ============================================================================
-- Maps event context (git_remote / cwd) to a destination organization per
-- user. Resolved server-side at first event of a session; the resolved
-- target_org_id is then frozen on sessions.org_id for the session lifetime.
--
-- Plan gating lives at the app layer, not the schema:
--   - scope='user' : all users can manage their own rules (free feature)
--   - scope='org'  : admin-managed org-wide templates, inherited by all
--                    members; visible to the app layer only on Team+ orgs
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.route_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    org_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE,
    scope TEXT NOT NULL DEFAULT 'user' CHECK (scope IN ('user', 'org')),
    priority INT NOT NULL DEFAULT 100,
    match_type TEXT NOT NULL CHECK (match_type IN ('git_remote', 'cwd')),
    match_pattern TEXT NOT NULL,
    target_org_id UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Exactly one of user_id or org_id is set, depending on scope.
    CONSTRAINT route_rules_scope_ownership CHECK (
        (scope = 'user' AND user_id IS NOT NULL AND org_id IS NULL)
        OR
        (scope = 'org' AND org_id IS NOT NULL AND user_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_route_rules_user ON public.route_rules(user_id, priority) WHERE scope = 'user';
CREATE INDEX IF NOT EXISTS idx_route_rules_org ON public.route_rules(org_id, priority) WHERE scope = 'org';
CREATE INDEX IF NOT EXISTS idx_route_rules_target ON public.route_rules(target_org_id);

-- Updated_at trigger
CREATE OR REPLACE FUNCTION update_route_rules_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS route_rules_updated_at ON public.route_rules;
CREATE TRIGGER route_rules_updated_at
    BEFORE UPDATE ON public.route_rules
    FOR EACH ROW
    EXECUTE FUNCTION update_route_rules_updated_at();

-- ============================================================================
-- RLS — user-scope rules are private to the owner; org-scope rules are
-- visible to all org members but only editable by owners/admins.
-- ============================================================================
ALTER TABLE public.route_rules ENABLE ROW LEVEL SECURITY;

-- Users read their own rules + any org-scope rules of orgs they belong to.
DROP POLICY IF EXISTS route_rules_select ON public.route_rules;
CREATE POLICY route_rules_select ON public.route_rules
    FOR SELECT
    USING (
        (scope = 'user' AND user_id = auth.uid())
        OR
        (scope = 'org' AND public.is_organization_member(org_id, auth.uid()))
    );

-- Users write their own user-scope rules.
DROP POLICY IF EXISTS route_rules_user_insert ON public.route_rules;
CREATE POLICY route_rules_user_insert ON public.route_rules
    FOR INSERT
    WITH CHECK (scope = 'user' AND user_id = auth.uid());

DROP POLICY IF EXISTS route_rules_user_update ON public.route_rules;
CREATE POLICY route_rules_user_update ON public.route_rules
    FOR UPDATE
    USING (scope = 'user' AND user_id = auth.uid())
    WITH CHECK (scope = 'user' AND user_id = auth.uid());

DROP POLICY IF EXISTS route_rules_user_delete ON public.route_rules;
CREATE POLICY route_rules_user_delete ON public.route_rules
    FOR DELETE
    USING (scope = 'user' AND user_id = auth.uid());

-- Admin-only management of org-scope rules.
DROP POLICY IF EXISTS route_rules_org_insert ON public.route_rules;
CREATE POLICY route_rules_org_insert ON public.route_rules
    FOR INSERT
    WITH CHECK (
        scope = 'org'
        AND EXISTS (
            SELECT 1 FROM public.organization_members
            WHERE organization_members.org_id = route_rules.org_id
              AND organization_members.user_id = auth.uid()
              AND organization_members.role IN ('owner', 'admin')
        )
    );

DROP POLICY IF EXISTS route_rules_org_update ON public.route_rules;
CREATE POLICY route_rules_org_update ON public.route_rules
    FOR UPDATE
    USING (
        scope = 'org'
        AND EXISTS (
            SELECT 1 FROM public.organization_members
            WHERE organization_members.org_id = route_rules.org_id
              AND organization_members.user_id = auth.uid()
              AND organization_members.role IN ('owner', 'admin')
        )
    );

DROP POLICY IF EXISTS route_rules_org_delete ON public.route_rules;
CREATE POLICY route_rules_org_delete ON public.route_rules
    FOR DELETE
    USING (
        scope = 'org'
        AND EXISTS (
            SELECT 1 FROM public.organization_members
            WHERE organization_members.org_id = route_rules.org_id
              AND organization_members.user_id = auth.uid()
              AND organization_members.role IN ('owner', 'admin')
        )
    );

COMMENT ON TABLE public.route_rules IS
    'Event routing rules — maps (match_pattern, match_type) to a target_org_id. Resolved server-side at first event of a session.';
