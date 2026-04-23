-- Issue #48 — second half. Paired with the code change flipping the default
-- Supabase client key from SUPABASE_ANON_KEY to SUPABASE_SERVICE_ROLE_KEY.
--
-- With backend services on the service_role (which bypasses RLS), we can
-- finally tighten the advisor-flagged spots without breaking those services:
--
--   1. SECURITY DEFINER views on user_profiles_with_email,
--      user_active_grants_enriched, user_groups_with_counts are bypassing
--      caller RLS → switch to security_invoker=true AND revoke anon SELECT.
--      user_profiles_with_email was leaking auth.users fields (email, phone,
--      last_sign_in_at, email_confirmed_at) to any anon-key holder.
--   2. `USING (true)` / `WITH CHECK (true)` on notifications INSERT and
--      invitations UPDATE meant any role with table access could write rows.
--      Restrict to service_role, which is what the backend uses now.
--   3. Functions with mutable search_path — ALTER ... SET search_path to pin
--      to the safe (public, pg_temp) pair. Zero behaviour change, silences
--      the advisor.
--   4. Debug helpers debug_auth_uid() / debug_auth_uid_eq(uuid) are unused
--      in application code (repo-wide grep confirms). Drop them.
--   5. sales_leads RLS enabled with zero policies — service_role bypasses,
--      but the advisor notes it. Add an explicit deny-all policy so intent
--      is readable.

BEGIN;

-- 1. View hardening -----------------------------------------------------------

ALTER VIEW public.user_profiles_with_email    SET (security_invoker = true);
ALTER VIEW public.user_active_grants_enriched SET (security_invoker = true);
ALTER VIEW public.user_groups_with_counts     SET (security_invoker = true);

REVOKE SELECT ON public.user_profiles_with_email    FROM anon;
REVOKE SELECT ON public.user_active_grants_enriched FROM anon;
REVOKE SELECT ON public.user_groups_with_counts     FROM anon;

-- Authenticated users can still query, RLS on the underlying tables filters
-- the rows they see. service_role bypasses RLS either way.

-- 2. Policy tightening --------------------------------------------------------

DROP POLICY IF EXISTS "System creates notifications" ON public.notifications;
CREATE POLICY "Service role creates notifications"
  ON public.notifications
  FOR INSERT
  TO service_role
  WITH CHECK (true);

DROP POLICY IF EXISTS "System can update invitation status" ON public.invitations;
CREATE POLICY "Service role updates invitation status"
  ON public.invitations
  FOR UPDATE
  TO service_role
  USING (true)
  WITH CHECK (true);

-- 3. Function search_path pins ------------------------------------------------

ALTER FUNCTION public.touch_profiles_updated_at()            SET search_path = public, pg_temp;
ALTER FUNCTION public.update_user_groups_updated_at()        SET search_path = public, pg_temp;
ALTER FUNCTION public.get_user_feature_via_groups(uuid, text)  SET search_path = public, pg_temp;
ALTER FUNCTION public.get_user_features_via_groups(uuid)     SET search_path = public, pg_temp;
ALTER FUNCTION public.get_group_member_count(uuid)           SET search_path = public, pg_temp;
ALTER FUNCTION public.update_webhooks_updated_at()           SET search_path = public, pg_temp;
ALTER FUNCTION public.update_updated_at_column()             SET search_path = public, pg_temp;
ALTER FUNCTION public.update_invitations_updated_at()        SET search_path = public, pg_temp;
ALTER FUNCTION public.update_workspaces_updated_at()         SET search_path = public, pg_temp;
ALTER FUNCTION public.update_organizations_updated_at()      SET search_path = public, pg_temp;
ALTER FUNCTION public.get_user_organizations(uuid)           SET search_path = public, pg_temp;
ALTER FUNCTION public.count_user_organizations(uuid)         SET search_path = public, pg_temp;
ALTER FUNCTION public.get_user_default_organization(uuid)    SET search_path = public, pg_temp;
ALTER FUNCTION public.is_organization_member(uuid, uuid)     SET search_path = public, pg_temp;
ALTER FUNCTION public.is_organization_admin(uuid, uuid)      SET search_path = public, pg_temp;
ALTER FUNCTION public.generate_organization_slug(text, uuid) SET search_path = public, pg_temp;
ALTER FUNCTION public.get_user_groups_with_details(uuid)     SET search_path = public, pg_temp;
ALTER FUNCTION public.update_route_rules_updated_at()        SET search_path = public, pg_temp;

-- 4. Drop unused debug helpers ------------------------------------------------

DROP FUNCTION IF EXISTS public.debug_auth_uid();
DROP FUNCTION IF EXISTS public.debug_auth_uid_eq(uuid);

-- 5. sales_leads explicit deny (readable intent) ------------------------------
-- No policies meant nobody but service_role could touch the table (service_role
-- bypasses RLS entirely). Add an explicit no-op policy naming the intent so
-- the linter quiets down and a future reader understands it's deliberate.

CREATE POLICY "Anon + authenticated have no access"
  ON public.sales_leads
  FOR ALL
  TO anon, authenticated
  USING (false)
  WITH CHECK (false);

COMMIT;
