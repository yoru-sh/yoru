-- Sales leads — captured from the public "Contact sales" form on yoru.sh
-- and from the in-dashboard "Contact sales" CTA on the Org plan card.
--
-- Privacy model: the form is unauthenticated public — the user may not even
-- have a Yoru account yet. We capture the bare minimum (email + company + a
-- free-text message + plan of interest) and email sales@yoru.sh on every
-- insert for immediate human follow-up. The row is the durable record.
--
-- RLS: no anon SELECT / UPDATE / DELETE. Service role only. The backend
-- inserts via service-role client; admins read via Supabase Studio.

CREATE TABLE IF NOT EXISTS public.sales_leads (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           text NOT NULL,
    company         text NOT NULL,
    seats_estimate  text,                   -- free-text ("~20", "50-100", "idk yet")
    use_case        text,
    source          text NOT NULL DEFAULT 'marketing',  -- 'marketing' | 'dashboard'
    referrer_url    text,
    user_agent      text,
    ip_hash         text,                   -- sha256(ip)[:16], not the raw IP
    -- fulfilment tracking, nullable until sales touches it
    handled_by      uuid REFERENCES auth.users(id) ON DELETE SET NULL,
    handled_at      timestamptz,
    notes           text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sales_leads_created_at    ON public.sales_leads (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sales_leads_email         ON public.sales_leads (email);
CREATE INDEX IF NOT EXISTS idx_sales_leads_unhandled     ON public.sales_leads (created_at DESC) WHERE handled_at IS NULL;

ALTER TABLE public.sales_leads ENABLE ROW LEVEL SECURITY;

-- Zero policies intentionally: anon + authenticated roles get no access.
-- Service role bypasses RLS, so the backend inserts land fine.
-- Admins read via Supabase Studio which uses the service role under the hood.
COMMENT ON TABLE public.sales_leads IS
  'Org-plan contact-sales form submissions. Service-role write/read only.';
