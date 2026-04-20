export type RedFlagKind =
  | "secret-pattern"
  | "shell-rm"
  | "migration-edit"
  | "env-mutation"
  | "ci-config-edit"

export type EventType = "tool_call" | "file_change" | "error" | "message"

export type FileOp = "create" | "edit" | "delete"

export interface Session {
  id: string
  user_email: string
  started_at: string
  ended_at: string | null
  duration_ms: number
  tool_count: number
  cost_usd: number
  flag_count: number
  flags: RedFlagKind[]
}

export interface SessionEvent {
  id: string
  session_id: string
  at: string
  type: EventType
  tool_name?: string
  tool_input?: unknown
  file_path?: string
  file_op?: FileOp
  error_message?: string
  text?: string
  flag?: RedFlagKind
  /** Tool stdout/stderr/error preview (capped 800 chars). */
  output?: string
  // SESSION-DETAIL-V1 additions (backend EventOut v1, all optional / non-breaking).
  tool?: string
  path?: string
  content?: string
  duration_ms?: number
  group_key?: string
}

export interface FileChanged {
  path: string
  op: FileOp
  additions: number
  deletions: number
}

export interface SessionDetail extends Session {
  events: SessionEvent[]
  files_changed: FileChanged[]
  summary?: string | null
}

export interface Summary {
  text: string
  model: string
  cached_at: string
}

export interface Filters {
  user?: string
  date_from?: string
  date_to?: string
  flag_only?: boolean
  min_cost?: number
}

export interface SessionList {
  items: Session[]
  total: number
}
