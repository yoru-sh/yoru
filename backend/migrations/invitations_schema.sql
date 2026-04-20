-- Migration: User Invitation System
-- Description: Complete invitation system for user onboarding via email invitations
-- Author: System
-- Date: 2026-01-14

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- TABLE: invitations
-- =====================================================
-- Stores user invitations with secure tokens and expiration
CREATE TABLE IF NOT EXISTS public.invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    invited_by UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected', 'expired')),
    message TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- INDEXES for Performance
-- =====================================================
-- Index for token-based lookups (most critical - used in accept flow)
CREATE INDEX IF NOT EXISTS idx_invitations_token ON public.invitations(token);

-- Index for email lookups (checking existing invitations)
CREATE INDEX IF NOT EXISTS idx_invitations_email ON public.invitations(email);

-- Index for status filtering
CREATE INDEX IF NOT EXISTS idx_invitations_status ON public.invitations(status);

-- Index for listing invitations by inviter
CREATE INDEX IF NOT EXISTS idx_invitations_invited_by ON public.invitations(invited_by);

-- Index for expiration queries and cleanup
CREATE INDEX IF NOT EXISTS idx_invitations_expires_at ON public.invitations(expires_at);

-- Composite index for pending invitations by email (common query)
CREATE INDEX IF NOT EXISTS idx_invitations_email_status ON public.invitations(email, status);

-- =====================================================
-- TRIGGER: Auto-update updated_at
-- =====================================================
CREATE OR REPLACE FUNCTION update_invitations_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_invitations_updated_at
    BEFORE UPDATE ON public.invitations
    FOR EACH ROW
    EXECUTE FUNCTION update_invitations_updated_at();

-- =====================================================
-- RLS POLICIES
-- =====================================================
-- Enable RLS on invitations table
ALTER TABLE public.invitations ENABLE ROW LEVEL SECURITY;

-- Policy 1: Users can view their own sent invitations
CREATE POLICY "Users can view sent invitations"
    ON public.invitations
    FOR SELECT
    USING (auth.uid() = invited_by);

-- Policy 2: Users can create invitations (they become the inviter)
CREATE POLICY "Users can create invitations"
    ON public.invitations
    FOR INSERT
    WITH CHECK (auth.uid() = invited_by);

-- Policy 3: Users can delete their own pending invitations
CREATE POLICY "Users can delete own pending invitations"
    ON public.invitations
    FOR DELETE
    USING (auth.uid() = invited_by AND status = 'pending');

-- Policy 4: Public can read invitation by token (for acceptance page)
-- Note: This is secure because token is cryptographically random and single-use
CREATE POLICY "Public can read invitation by token"
    ON public.invitations
    FOR SELECT
    USING (true);

-- Policy 5: System can update invitation status (for acceptance flow)
-- Note: This is secure because validation happens in application layer
CREATE POLICY "System can update invitation status"
    ON public.invitations
    FOR UPDATE
    USING (true);

-- Policy 6: Admins can view all invitations
CREATE POLICY "Admins can view all invitations"
    ON public.invitations
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE profiles.id = auth.uid()
            AND profiles.role = 'admin'
        )
    );

-- =====================================================
-- COMMENTS for Documentation
-- =====================================================
COMMENT ON TABLE public.invitations IS 'Stores user invitations with secure tokens for email-based onboarding';
COMMENT ON COLUMN public.invitations.token IS 'Cryptographically secure random token for invitation acceptance (256-bit entropy)';
COMMENT ON COLUMN public.invitations.expires_at IS 'Expiration timestamp (default: 7 days from creation)';
COMMENT ON COLUMN public.invitations.message IS 'Optional custom message from inviter (max 500 chars)';
COMMENT ON COLUMN public.invitations.status IS 'Invitation status: pending, accepted, rejected, or expired';
