import { useEffect, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { apiFetch } from "../lib/api"
import { toast } from "../components/Toaster"

interface UserResponse {
  id: string
  email: string
  first_name?: string | null
  last_name?: string | null
  avatar_url?: string | null
  locale?: string | null
  timezone?: string | null
  created_at?: string
  updated_at?: string
}

interface UserUpdate {
  first_name?: string | null
  last_name?: string | null
  avatar_url?: string | null
  locale?: string | null
  timezone?: string | null
}

const ME_KEY = ["me"] as const

async function fetchMe(): Promise<UserResponse> {
  return apiFetch<UserResponse>("/me")
}

async function patchMe(patch: UserUpdate): Promise<UserResponse> {
  return apiFetch<UserResponse>("/me", {
    method: "PATCH",
    body: JSON.stringify(patch),
  })
}

// A browser locales + timezones shortlist for the select. Falls back to free-text.
const LOCALES = ["en", "fr", "de", "es", "it", "pt", "ja", "zh"]
const TIMEZONES = [
  "UTC",
  "Europe/Paris",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Los_Angeles",
  "Asia/Tokyo",
  "Asia/Shanghai",
]

export function ProfilePage() {
  const qc = useQueryClient()

  const { data: me, isLoading } = useQuery({ queryKey: ME_KEY, queryFn: fetchMe })

  const [firstName, setFirstName] = useState("")
  const [lastName, setLastName] = useState("")
  const [avatarUrl, setAvatarUrl] = useState("")
  const [locale, setLocale] = useState("en")
  const [timezone, setTimezone] = useState("UTC")

  useEffect(() => {
    if (!me) return
    setFirstName(me.first_name ?? "")
    setLastName(me.last_name ?? "")
    setAvatarUrl(me.avatar_url ?? "")
    setLocale(me.locale ?? "en")
    setTimezone(me.timezone ?? "UTC")
  }, [me])

  const update = useMutation({
    mutationFn: patchMe,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ME_KEY })
      qc.invalidateQueries({ queryKey: ["me"] }) // refresh the header user too
      toast.success("Profile saved")
    },
    onError: (err) => toast.error("Save failed", err instanceof Error ? err.message : String(err)),
  })

  function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    update.mutate({
      first_name: firstName.trim() || null,
      last_name:  lastName.trim() || null,
      avatar_url: avatarUrl.trim() || null,
      locale,
      timezone,
    })
  }

  const initials = (firstName[0] ?? me?.email[0] ?? "?").toUpperCase() +
    (lastName[0] ?? "").toUpperCase()

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <p className="font-mono text-caption uppercase tracking-wider text-ink-muted">Settings</p>
        <h1 className="mt-2 font-sans text-3xl font-semibold text-ink">Profile</h1>
        <p className="mt-2 text-sm text-ink-muted">
          Update your display name, avatar, locale, and timezone.
        </p>
      </div>

      {isLoading ? (
        <p className="text-sm text-ink-muted">Loading…</p>
      ) : (
        <form onSubmit={onSubmit} className="space-y-5 rounded border border-rule bg-surface p-5">
          <div className="flex items-center gap-4">
            <div
              aria-hidden="true"
              className="relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full border border-rule bg-sunken font-mono text-lg font-semibold text-ink"
            >
              {avatarUrl ? (
                <img src={avatarUrl} alt="" className="h-full w-full object-cover" onError={(e) => {
                  (e.currentTarget.style.display = "none")
                }} />
              ) : null}
              <span className="absolute inset-0 flex items-center justify-center">
                {initials}
              </span>
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-ink">{me?.email}</p>
              <p className="font-mono text-micro text-ink-faint">user {me?.id.slice(0, 8)}…</p>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <Field label="First name">
              <Input value={firstName} onChange={setFirstName} />
            </Field>
            <Field label="Last name">
              <Input value={lastName} onChange={setLastName} />
            </Field>
          </div>

          <Field label="Avatar URL" hint="Paste a public URL (Gravatar, GitHub, etc.)">
            <Input value={avatarUrl} onChange={setAvatarUrl} placeholder="https://…" />
          </Field>

          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Locale">
              <select
                value={locale}
                onChange={(e) => setLocale(e.target.value)}
                className="w-full rounded-sm border border-rule bg-paper px-2 py-1.5 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
              >
                {LOCALES.map((l) => (
                  <option key={l} value={l}>{l}</option>
                ))}
              </select>
            </Field>
            <Field label="Timezone">
              <select
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                className="w-full rounded-sm border border-rule bg-paper px-2 py-1.5 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
              >
                {TIMEZONES.map((tz) => (
                  <option key={tz} value={tz}>{tz}</option>
                ))}
              </select>
            </Field>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              type="submit"
              disabled={update.isPending}
              className="inline-flex min-h-[36px] items-center gap-2 rounded-sm bg-accent-500 px-4 py-1 font-mono text-caption font-semibold uppercase tracking-wider text-paper hover:bg-accent-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 disabled:opacity-60"
            >
              {update.isPending && (
                <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
                  <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
                </svg>
              )}
              {update.isPending ? "Saving…" : "Save changes"}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="font-mono text-micro uppercase tracking-wider text-ink-muted">{label}</span>
      <div className="mt-1">{children}</div>
      {hint && <p className="mt-1 font-mono text-micro text-ink-faint">{hint}</p>}
    </label>
  )
}

function Input({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-sm border border-rule bg-paper px-2 py-1.5 text-sm text-ink outline-none focus-visible:ring-2 focus-visible:ring-accent-500"
    />
  )
}
