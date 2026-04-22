import { useQuery } from "@tanstack/react-query"
import { apiFetch } from "./api"

export interface FeatureValue {
  key: string
  value: unknown
  source: "grant" | "plan" | "default" | "unknown"
  type: "flag" | "quota" | null
}

/**
 * Read a feature's effective value for the current user.
 * Resolution (server-side): user_grants → plan_features → default.
 * Caller decides how to interpret value (e.g. `{limit: N}` for quotas,
 * `{enabled: bool}` for flags).
 */
export function useFeature(key: string) {
  return useQuery<FeatureValue>({
    queryKey: ["me", "feature", key],
    queryFn: () => apiFetch<FeatureValue>(`/me/features/${key}`),
    staleTime: 60_000,
  })
}

export function extractQuotaLimit(feature: FeatureValue | undefined): number | null {
  if (!feature) return null
  const v = feature.value as { limit?: number } | null
  if (!v) return null
  if (typeof v.limit === "number") return v.limit
  return null
}

export function extractFlag(feature: FeatureValue | undefined): boolean {
  if (!feature) return false
  const v = feature.value as { enabled?: boolean } | null
  if (!v) return false
  return Boolean(v.enabled)
}
