// Deprecated. Dashboard auth is cookie-based via lib/auth-api.ts — the
// Supabase JS client is no longer used on the frontend. Kept as an empty
// module to avoid breaking any lingering import during the migration.
//
// Remove `@supabase/supabase-js` from package.json once all usages are
// verified gone (grep `supabase` in src/ should return only this file +
// docs).
export {}
