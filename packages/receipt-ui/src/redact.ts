// Token-shape redaction for expanded-row display. Masks secret-looking
// substrings in the timeline detail view so a viewer can still see the event
// shape without the raw token leaking to shoulder-surfers or screenshots.
// Keep the first N chars so the user can correlate the fingerprint across
// logs/DB. Extend the array when a new token shape shows up in tool_response.

const _TOKEN_REDACT_RES: RegExp[] = [
  /\brcpt_[A-Za-z0-9_-]{8,}/g,                  // Receipt hook tokens
  /\bsk_(?:live|test)_[A-Za-z0-9]{8,}/g,        // Stripe
  /\bAKIA[0-9A-Z]{12,}/g,                       // AWS access key
  /\bghp_[A-Za-z0-9]{12,}/g,                    // GitHub PAT (new)
  /\bgho_[A-Za-z0-9]{12,}/g,                    // GitHub OAuth
  /\bBearer\s+[A-Za-z0-9_\-.]{16,}/g,           // Raw bearer headers
  /\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g, // JWTs
]

export function redactTokens(s: string): string {
  let out = s
  for (const re of _TOKEN_REDACT_RES) {
    out = out.replace(re, (m) => {
      const kept = m.slice(0, Math.min(12, m.length))
      return `${kept}…[redacted]`
    })
  }
  return out
}
