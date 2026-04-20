-- =============================================
-- User Groups Schema Migration
-- =============================================
-- Description: RBAC user groups system with dynamic permission management
-- Tables: user_groups, user_group_members, user_group_features
-- Features: RLS policies, SQL helper functions, audit trails
-- =============================================

-- =============================================
-- Table: user_groups
-- =============================================
-- Description: Groups for organizing users with shared permissions
CREATE TABLE IF NOT EXISTS public.user_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    is_active BOOLEAN DEFAULT true,
    created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for performance on name lookups
CREATE INDEX IF NOT EXISTS idx_user_groups_name ON public.user_groups(name);

-- Index for filtering active groups
CREATE INDEX IF NOT EXISTS idx_user_groups_is_active ON public.user_groups(is_active);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_user_groups_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER user_groups_updated_at
    BEFORE UPDATE ON public.user_groups
    FOR EACH ROW
    EXECUTE FUNCTION update_user_groups_updated_at();

-- =============================================
-- Table: user_group_members
-- =============================================
-- Description: Many-to-many relationship between users and groups
CREATE TABLE IF NOT EXISTS public.user_group_members (
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    group_id UUID REFERENCES public.user_groups(id) ON DELETE CASCADE,
    added_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    added_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, group_id)
);

-- Index for querying user's groups
CREATE INDEX IF NOT EXISTS idx_user_group_members_user_id ON public.user_group_members(user_id);

-- Index for querying group's members
CREATE INDEX IF NOT EXISTS idx_user_group_members_group_id ON public.user_group_members(group_id);

-- =============================================
-- Table: user_group_features
-- =============================================
-- Description: Features assigned to groups with their values
CREATE TABLE IF NOT EXISTS public.user_group_features (
    group_id UUID REFERENCES public.user_groups(id) ON DELETE CASCADE,
    feature_id UUID REFERENCES public.features(id) ON DELETE CASCADE,
    value JSONB NOT NULL,
    added_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (group_id, feature_id)
);

-- Index for querying group's features
CREATE INDEX IF NOT EXISTS idx_user_group_features_group_id ON public.user_group_features(group_id);

-- Index for querying feature assignments
CREATE INDEX IF NOT EXISTS idx_user_group_features_feature_id ON public.user_group_features(feature_id);

-- =============================================
-- RLS Policies
-- =============================================

-- Enable RLS on all tables
ALTER TABLE public.user_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_group_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_group_features ENABLE ROW LEVEL SECURITY;

-- =============================================
-- Policies: user_groups
-- =============================================

-- Admins can manage all groups
CREATE POLICY "Admins can manage groups"
    ON public.user_groups FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- Users can view active groups they belong to
CREATE POLICY "Users can view own groups"
    ON public.user_groups FOR SELECT
    USING (
        is_active = true
        AND EXISTS (
            SELECT 1 FROM public.user_group_members
            WHERE group_id = user_groups.id
            AND user_id = auth.uid()
        )
    );

-- =============================================
-- Policies: user_group_members
-- =============================================

-- Admins can manage all members
CREATE POLICY "Admins can manage members"
    ON public.user_group_members FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- Users can view their own group memberships
CREATE POLICY "Users can view own memberships"
    ON public.user_group_members FOR SELECT
    USING (auth.uid() = user_id);

-- =============================================
-- Policies: user_group_features
-- =============================================

-- Admins can manage all group features
CREATE POLICY "Admins can manage group features"
    ON public.user_group_features FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- Users can view features of their groups
CREATE POLICY "Users can view own group features"
    ON public.user_group_features FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.user_group_members
            WHERE group_id = user_group_features.group_id
            AND user_id = auth.uid()
        )
        AND EXISTS (
            SELECT 1 FROM public.user_groups
            WHERE id = user_group_features.group_id
            AND is_active = true
        )
    );

-- =============================================
-- SQL Helper Functions
-- =============================================

-- Function to get user's feature value via groups
-- Returns the first matching feature value if user is in any group with that feature
CREATE OR REPLACE FUNCTION get_user_feature_via_groups(
    p_user_id UUID,
    p_feature_key TEXT
)
RETURNS TABLE(value JSONB) AS $$
BEGIN
    RETURN QUERY
    SELECT ugf.value
    FROM public.user_group_features ugf
    JOIN public.user_group_members ugm ON ugf.group_id = ugm.group_id
    JOIN public.features f ON ugf.feature_id = f.id
    JOIN public.user_groups ug ON ugf.group_id = ug.id
    WHERE ugm.user_id = p_user_id
      AND f.key = p_feature_key
      AND ug.is_active = true
    LIMIT 1;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get all features for a user via groups
CREATE OR REPLACE FUNCTION get_user_features_via_groups(
    p_user_id UUID
)
RETURNS TABLE(
    feature_id UUID,
    feature_key TEXT,
    feature_name TEXT,
    value JSONB,
    group_id UUID,
    group_name TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        f.id as feature_id,
        f.key as feature_key,
        f.name as feature_name,
        ugf.value,
        ug.id as group_id,
        ug.name as group_name
    FROM public.user_group_features ugf
    JOIN public.user_group_members ugm ON ugf.group_id = ugm.group_id
    JOIN public.features f ON ugf.feature_id = f.id
    JOIN public.user_groups ug ON ugf.group_id = ug.id
    WHERE ugm.user_id = p_user_id
      AND ug.is_active = true
    ORDER BY ug.name, f.name;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Function to get members count for a group
CREATE OR REPLACE FUNCTION get_group_member_count(
    p_group_id UUID
)
RETURNS INTEGER AS $$
DECLARE
    member_count INTEGER;
BEGIN
    SELECT COUNT(*)
    INTO member_count
    FROM public.user_group_members
    WHERE group_id = p_group_id;

    RETURN member_count;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- =============================================
-- Comments
-- =============================================

COMMENT ON TABLE public.user_groups IS 'Groups for organizing users with shared permissions';
COMMENT ON TABLE public.user_group_members IS 'Many-to-many relationship between users and groups';
COMMENT ON TABLE public.user_group_features IS 'Features assigned to groups with their values';

COMMENT ON FUNCTION get_user_feature_via_groups IS 'Get a specific feature value for a user via their group memberships';
COMMENT ON FUNCTION get_user_features_via_groups IS 'Get all features for a user via their group memberships';
COMMENT ON FUNCTION get_group_member_count IS 'Get the number of members in a group';
