-- Subscription System Schema Migration
-- Creates tables for plans, features, subscriptions, promo codes, and user grants

-- ============================================================================
-- TABLE: plans
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    billing_period TEXT NOT NULL CHECK (billing_period IN ('monthly', 'annual', 'one_time')),
    is_active BOOLEAN DEFAULT true,
    is_custom BOOLEAN DEFAULT false,
    created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_plans_billing_period ON public.plans(billing_period);
CREATE INDEX idx_plans_is_active ON public.plans(is_active);
CREATE INDEX idx_plans_is_custom ON public.plans(is_custom);

-- RLS policies for plans
ALTER TABLE public.plans ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can view active plans"
    ON public.plans FOR SELECT
    USING (is_active = true);

CREATE POLICY "Admins can manage plans"
    ON public.plans FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- ============================================================================
-- TABLE: features
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.features (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    type TEXT NOT NULL CHECK (type IN ('flag', 'quota')),
    default_value JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_features_key ON public.features(key);
CREATE INDEX idx_features_type ON public.features(type);

-- RLS policies for features
ALTER TABLE public.features ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can view features"
    ON public.features FOR SELECT
    USING (true);

CREATE POLICY "Admins can manage features"
    ON public.features FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- ============================================================================
-- TABLE: plan_features (junction table)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.plan_features (
    plan_id UUID REFERENCES public.plans(id) ON DELETE CASCADE,
    feature_id UUID REFERENCES public.features(id) ON DELETE CASCADE,
    value JSONB NOT NULL,
    PRIMARY KEY (plan_id, feature_id)
);

CREATE INDEX idx_plan_features_plan ON public.plan_features(plan_id);
CREATE INDEX idx_plan_features_feature ON public.plan_features(feature_id);

-- RLS policies for plan_features
ALTER TABLE public.plan_features ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can view plan features"
    ON public.plan_features FOR SELECT
    USING (true);

CREATE POLICY "Admins can manage plan features"
    ON public.plan_features FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- ============================================================================
-- TABLE: promo_codes
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.promo_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK (type IN ('percentage', 'fixed')),
    value DECIMAL(10, 2) NOT NULL,
    max_uses INT,
    current_uses INT DEFAULT 0,
    expires_at TIMESTAMPTZ,
    conditions JSONB,
    is_active BOOLEAN DEFAULT true,
    created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_promo_codes_code ON public.promo_codes(code);
CREATE INDEX idx_promo_codes_is_active ON public.promo_codes(is_active);
CREATE INDEX idx_promo_codes_expires_at ON public.promo_codes(expires_at);

-- RLS policies for promo_codes
ALTER TABLE public.promo_codes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Anyone can view active promo codes"
    ON public.promo_codes FOR SELECT
    USING (is_active = true AND (expires_at IS NULL OR expires_at > NOW()));

CREATE POLICY "Admins can manage promo codes"
    ON public.promo_codes FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- ============================================================================
-- TABLE: subscriptions
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    plan_id UUID REFERENCES public.plans(id) ON DELETE RESTRICT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled', 'expired', 'pending')),
    start_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    end_date TIMESTAMPTZ,
    promo_code_id UUID REFERENCES public.promo_codes(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_subscriptions_user ON public.subscriptions(user_id);
CREATE INDEX idx_subscriptions_plan ON public.subscriptions(plan_id);
CREATE INDEX idx_subscriptions_status ON public.subscriptions(status);

-- RLS policies for subscriptions
ALTER TABLE public.subscriptions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own subscriptions"
    ON public.subscriptions FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can create own subscriptions"
    ON public.subscriptions FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Admins can view all subscriptions"
    ON public.subscriptions FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );

-- ============================================================================
-- TABLE: promo_usages
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.promo_usages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    promo_code_id UUID REFERENCES public.promo_codes(id) ON DELETE CASCADE NOT NULL,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    subscription_id UUID REFERENCES public.subscriptions(id) ON DELETE CASCADE,
    used_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_promo_usages_promo ON public.promo_usages(promo_code_id);
CREATE INDEX idx_promo_usages_user ON public.promo_usages(user_id);
CREATE INDEX idx_promo_usages_subscription ON public.promo_usages(subscription_id);

-- RLS policies for promo_usages
ALTER TABLE public.promo_usages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own promo usages"
    ON public.promo_usages FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "System can create promo usages"
    ON public.promo_usages FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- ============================================================================
-- TABLE: user_grants (Administrative grants to override plan features)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.user_grants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
    feature_id UUID REFERENCES public.features(id) ON DELETE CASCADE NOT NULL,
    value JSONB NOT NULL,
    reason TEXT,
    granted_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, feature_id)
);

CREATE INDEX idx_user_grants_user ON public.user_grants(user_id);
CREATE INDEX idx_user_grants_feature ON public.user_grants(feature_id);
CREATE INDEX idx_user_grants_expires ON public.user_grants(expires_at);

-- RLS policies for user_grants
ALTER TABLE public.user_grants ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view own grants"
    ON public.user_grants FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Admins can manage grants"
    ON public.user_grants FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM public.profiles
            WHERE id = auth.uid() AND role = 'admin'
        )
    );
