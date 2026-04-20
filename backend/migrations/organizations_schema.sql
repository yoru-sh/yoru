-- Organizations Multi-Tenancy Schema Migration
-- Progressive organization system with hidden personal orgs for B2C users
-- Author: System
-- Date: 2026-01-16

-- ============================================================================
-- TABLE: organizations
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL DEFAULT 'team' CHECK (type IN ('personal', 'team')),
    owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    avatar_url TEXT,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted_at TIMESTAMPTZ  -- Soft delete support (30-day recovery)
);

-- Indexes for organizations
CREATE INDEX IF NOT EXISTS idx_organizations_owner_id ON public.organizations(owner_id);
CREATE INDEX IF NOT EXISTS idx_organizations_type ON public.organizations(type);
CREATE INDEX IF NOT EXISTS idx_organizations_slug ON public.organizations(slug);
CREATE INDEX IF NOT EXISTS idx_organizations_deleted_at ON public.organizations(deleted_at)
    WHERE deleted_at IS NULL;

-- ============================================================================
-- TABLE: organization_members
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.organization_members (
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
    joined_at TIMESTAMPTZ DEFAULT NOW(),
    invited_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    PRIMARY KEY (org_id, user_id)
);

-- Indexes for organization_members
CREATE INDEX IF NOT EXISTS idx_organization_members_user_id ON public.organization_members(user_id);
CREATE INDEX IF NOT EXISTS idx_organization_members_org_id ON public.organization_members(org_id);
CREATE INDEX IF NOT EXISTS idx_organization_members_role ON public.organization_members(role);

-- ============================================================================
-- TABLE: organization_invitations
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.organization_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    token TEXT UNIQUE NOT NULL,
    invited_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ DEFAULT (NOW() + interval '7 days'),
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for organization_invitations
CREATE INDEX IF NOT EXISTS idx_organization_invitations_org_id ON public.organization_invitations(org_id);
CREATE INDEX IF NOT EXISTS idx_organization_invitations_email ON public.organization_invitations(email);
CREATE INDEX IF NOT EXISTS idx_organization_invitations_token ON public.organization_invitations(token);
CREATE INDEX IF NOT EXISTS idx_organization_invitations_expires_at ON public.organization_invitations(expires_at);

-- ============================================================================
-- TRIGGER: Auto-update updated_at for organizations
-- ============================================================================
CREATE OR REPLACE FUNCTION update_organizations_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_organizations_updated_at
    BEFORE UPDATE ON public.organizations
    FOR EACH ROW
    EXECUTE FUNCTION update_organizations_updated_at();

-- ============================================================================
-- MODIFY EXISTING TABLES: Add org_id support
-- ============================================================================

-- Add org_id to subscriptions (move billing to org level)
ALTER TABLE public.subscriptions
    ADD COLUMN IF NOT EXISTS org_id UUID REFERENCES public.organizations(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_subscriptions_org_id ON public.subscriptions(org_id);

-- Add org_id to webhooks
ALTER TABLE public.webhooks
    ADD COLUMN IF NOT EXISTS org_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_webhooks_org_id ON public.webhooks(org_id);

-- Add org_id to notifications (for org-wide notifications)
ALTER TABLE public.notifications
    ADD COLUMN IF NOT EXISTS org_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_notifications_org_id ON public.notifications(org_id);

-- ============================================================================
-- RLS POLICIES: organizations
-- ============================================================================
ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;

-- Members can view their organizations (exclude soft-deleted)
CREATE POLICY "Members can view organizations"
    ON public.organizations FOR SELECT
    USING (
        deleted_at IS NULL
        AND id IN (
            SELECT org_id FROM public.organization_members
            WHERE user_id = auth.uid()
        )
    );

-- Users can create organizations
CREATE POLICY "Users can create organizations"
    ON public.organizations FOR INSERT
    WITH CHECK (auth.uid() = owner_id);

-- Owners and admins can update their organizations
CREATE POLICY "Admins can update organizations"
    ON public.organizations FOR UPDATE
    USING (
        id IN (
            SELECT org_id FROM public.organization_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

-- Only owners can soft delete their organizations
CREATE POLICY "Owners can delete organizations"
    ON public.organizations FOR DELETE
    USING (
        owner_id = auth.uid()
    );

-- ============================================================================
-- RLS POLICIES: organization_members
-- ============================================================================
ALTER TABLE public.organization_members ENABLE ROW LEVEL SECURITY;

-- Members can view other members in their organizations
CREATE POLICY "Members can view org members"
    ON public.organization_members FOR SELECT
    USING (
        org_id IN (
            SELECT id FROM public.organizations
            WHERE deleted_at IS NULL
            AND id IN (
                SELECT org_id FROM public.organization_members
                WHERE user_id = auth.uid()
            )
        )
    );

-- Admins and owners can add members
CREATE POLICY "Admins can add members"
    ON public.organization_members FOR INSERT
    WITH CHECK (
        org_id IN (
            SELECT org_id FROM public.organization_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

-- Admins and owners can update member roles
CREATE POLICY "Admins can update members"
    ON public.organization_members FOR UPDATE
    USING (
        org_id IN (
            SELECT org_id FROM public.organization_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

-- Admins and owners can remove members (except owner)
CREATE POLICY "Admins can remove members"
    ON public.organization_members FOR DELETE
    USING (
        org_id IN (
            SELECT org_id FROM public.organization_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
        AND role != 'owner'  -- Cannot remove owner
    );

-- Members can leave organizations (except owner)
CREATE POLICY "Members can leave organizations"
    ON public.organization_members FOR DELETE
    USING (
        user_id = auth.uid()
        AND role != 'owner'  -- Owner cannot leave, must transfer or delete
    );

-- ============================================================================
-- RLS POLICIES: organization_invitations
-- ============================================================================
ALTER TABLE public.organization_invitations ENABLE ROW LEVEL SECURITY;

-- Admins and owners can view invitations for their orgs
CREATE POLICY "Admins can view org invitations"
    ON public.organization_invitations FOR SELECT
    USING (
        org_id IN (
            SELECT org_id FROM public.organization_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

-- Users can view invitations sent to their email
CREATE POLICY "Users can view own invitations"
    ON public.organization_invitations FOR SELECT
    USING (
        email = (SELECT email FROM auth.users WHERE id = auth.uid())
    );

-- Admins and owners can create invitations
CREATE POLICY "Admins can create invitations"
    ON public.organization_invitations FOR INSERT
    WITH CHECK (
        org_id IN (
            SELECT org_id FROM public.organization_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

-- Admins and owners can cancel invitations
CREATE POLICY "Admins can delete invitations"
    ON public.organization_invitations FOR DELETE
    USING (
        org_id IN (
            SELECT org_id FROM public.organization_members
            WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
        )
    );

-- Anyone can update invitation (for accepting)
CREATE POLICY "Users can accept invitations"
    ON public.organization_invitations FOR UPDATE
    USING (
        email = (SELECT email FROM auth.users WHERE id = auth.uid())
    );

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to get user's organizations
CREATE OR REPLACE FUNCTION get_user_organizations(p_user_id UUID)
RETURNS TABLE (
    org_id UUID,
    org_name TEXT,
    org_slug TEXT,
    org_type TEXT,
    user_role TEXT,
    is_owner BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        o.id AS org_id,
        o.name AS org_name,
        o.slug AS org_slug,
        o.type AS org_type,
        om.role AS user_role,
        o.owner_id = p_user_id AS is_owner
    FROM public.organizations o
    INNER JOIN public.organization_members om ON o.id = om.org_id
    WHERE om.user_id = p_user_id
    AND o.deleted_at IS NULL
    ORDER BY o.created_at;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to count user's organizations
CREATE OR REPLACE FUNCTION count_user_organizations(p_user_id UUID)
RETURNS INTEGER AS $$
BEGIN
    RETURN (
        SELECT COUNT(*)::INTEGER
        FROM public.organization_members om
        INNER JOIN public.organizations o ON o.id = om.org_id
        WHERE om.user_id = p_user_id
        AND o.deleted_at IS NULL
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get user's default organization (personal org or first org)
CREATE OR REPLACE FUNCTION get_user_default_organization(p_user_id UUID)
RETURNS UUID AS $$
DECLARE
    v_org_id UUID;
BEGIN
    -- First, try to find personal org
    SELECT o.id INTO v_org_id
    FROM public.organizations o
    INNER JOIN public.organization_members om ON o.id = om.org_id
    WHERE om.user_id = p_user_id
    AND o.type = 'personal'
    AND o.deleted_at IS NULL
    LIMIT 1;

    -- If no personal org, get first org
    IF v_org_id IS NULL THEN
        SELECT o.id INTO v_org_id
        FROM public.organizations o
        INNER JOIN public.organization_members om ON o.id = om.org_id
        WHERE om.user_id = p_user_id
        AND o.deleted_at IS NULL
        ORDER BY o.created_at
        LIMIT 1;
    END IF;

    RETURN v_org_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to check if user is member of organization
CREATE OR REPLACE FUNCTION is_organization_member(p_user_id UUID, p_org_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1
        FROM public.organization_members om
        INNER JOIN public.organizations o ON o.id = om.org_id
        WHERE om.user_id = p_user_id
        AND om.org_id = p_org_id
        AND o.deleted_at IS NULL
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to check if user is admin or owner of organization
CREATE OR REPLACE FUNCTION is_organization_admin(p_user_id UUID, p_org_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1
        FROM public.organization_members om
        INNER JOIN public.organizations o ON o.id = om.org_id
        WHERE om.user_id = p_user_id
        AND om.org_id = p_org_id
        AND om.role IN ('owner', 'admin')
        AND o.deleted_at IS NULL
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to generate unique slug from name
CREATE OR REPLACE FUNCTION generate_organization_slug(p_name TEXT, p_owner_id UUID)
RETURNS TEXT AS $$
DECLARE
    v_base_slug TEXT;
    v_slug TEXT;
    v_counter INTEGER := 0;
BEGIN
    -- Create base slug from name
    v_base_slug := lower(regexp_replace(p_name, '[^a-zA-Z0-9]+', '-', 'g'));
    v_base_slug := regexp_replace(v_base_slug, '^-+|-+$', '', 'g');

    -- For personal orgs, use 'personal-{user_id_prefix}'
    IF p_name = 'Personal' THEN
        v_slug := 'personal-' || substr(p_owner_id::text, 1, 8);
        RETURN v_slug;
    END IF;

    -- Try base slug first
    v_slug := v_base_slug;

    -- Add counter if slug exists
    WHILE EXISTS (SELECT 1 FROM public.organizations WHERE slug = v_slug) LOOP
        v_counter := v_counter + 1;
        v_slug := v_base_slug || '-' || v_counter;
    END LOOP;

    RETURN v_slug;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON TABLE public.organizations IS 'Organizations (workspaces/tenants) for multi-tenancy support';
COMMENT ON COLUMN public.organizations.type IS 'personal = auto-created hidden org for B2C, team = visible collaborative org';
COMMENT ON COLUMN public.organizations.deleted_at IS 'Soft delete timestamp for 30-day recovery period';
COMMENT ON COLUMN public.organizations.settings IS 'Organization-specific settings as JSON';

COMMENT ON TABLE public.organization_members IS 'Organization membership with role-based access';
COMMENT ON COLUMN public.organization_members.role IS 'owner = full control, admin = manage members/settings, member = basic access';

COMMENT ON TABLE public.organization_invitations IS 'Pending invitations to join organizations';
COMMENT ON COLUMN public.organization_invitations.token IS 'Unique token for invitation URL';
