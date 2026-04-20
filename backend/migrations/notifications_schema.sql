-- Migration: Notifications In-App System
-- Description: Complete notification system with bell icon, unread count, pagination and admin broadcast
-- Author: System
-- Date: 2026-01-14

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =====================================================
-- FUNCTION: Auto-update updated_at column
-- =====================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =====================================================
-- TABLE: public.notifications
-- =====================================================
CREATE TABLE IF NOT EXISTS public.notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Type de notification
    type TEXT NOT NULL CHECK (type IN ('info', 'success', 'warning', 'error')),

    -- Contenu
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    action_url TEXT,

    -- Metadata additionnelles (JSON)
    metadata JSONB DEFAULT '{}',

    -- Statut lecture
    is_read BOOLEAN DEFAULT FALSE,
    read_at TIMESTAMPTZ,

    -- Broadcast system (NULL = notification user, NOT NULL = notification système)
    broadcast_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =====================================================
-- INDEXES (performance critique)
-- =====================================================

-- Index principal : user_id (toutes les queries filtrent par user)
CREATE INDEX IF NOT EXISTS idx_notifications_user_id
    ON public.notifications(user_id);

-- Index partial : notifications non lues par user (pour unread_count)
CREATE INDEX IF NOT EXISTS idx_notifications_user_unread
    ON public.notifications(user_id, is_read)
    WHERE is_read = FALSE;

-- Index : tri par date (pagination)
CREATE INDEX IF NOT EXISTS idx_notifications_created_at
    ON public.notifications(created_at DESC);

-- Index : broadcast system
CREATE INDEX IF NOT EXISTS idx_notifications_broadcast
    ON public.notifications(broadcast_by)
    WHERE broadcast_by IS NOT NULL;

-- Composite index for efficient pagination per user
CREATE INDEX IF NOT EXISTS idx_notifications_user_created
    ON public.notifications(user_id, created_at DESC);

-- =====================================================
-- TRIGGER : Auto-update updated_at
-- =====================================================
CREATE TRIGGER update_notifications_updated_at
    BEFORE UPDATE ON public.notifications
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =====================================================
-- RLS POLICIES
-- =====================================================
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

-- Policy 1: Users can view their own notifications
CREATE POLICY "Users view own notifications"
    ON public.notifications FOR SELECT
    USING (auth.uid() = user_id);

-- Policy 2: Users can update their own notifications (mark as read)
CREATE POLICY "Users update own notifications"
    ON public.notifications FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Policy 3: Users can delete their own notifications
CREATE POLICY "Users delete own notifications"
    ON public.notifications FOR DELETE
    USING (auth.uid() = user_id);

-- Policy 4: System can create notifications (service layer with authenticated users)
CREATE POLICY "System creates notifications"
    ON public.notifications FOR INSERT
    WITH CHECK (true);

-- Policy 5: Admins can view all notifications (for admin dashboard)
CREATE POLICY "Admins view all notifications"
    ON public.notifications FOR SELECT
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
COMMENT ON TABLE public.notifications IS 'In-app notification system with user and admin broadcast support';
COMMENT ON COLUMN public.notifications.type IS 'Notification type: info, success, warning, or error';
COMMENT ON COLUMN public.notifications.metadata IS 'Additional JSON metadata for the notification';
COMMENT ON COLUMN public.notifications.is_read IS 'Whether the notification has been read by the user';
COMMENT ON COLUMN public.notifications.broadcast_by IS 'Admin ID if system broadcast, NULL for regular user notifications';
