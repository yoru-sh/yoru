"""Session scoring — counterbalanced multi-dimensional quality signal.

Methodology anchored in three established frameworks (see references at end):

  * DX Core 4 (Noda/Forsgren/Storey/Greiler, 2024) — unifies DORA + SPACE +
    DevEx into four *counterbalanced* dimensions. Counterbalancing is the
    anti-gaming guardrail: Speed without Quality is penalized structurally.
  * SPACE (Microsoft Research, 2021) — at least 3 axes required for an
    honest composite (single-axis lies).
  * SWE-bench + trajectory-reduction papers (arxiv 2509.23586, 2510.18170) —
    tool-call metrics for agent runs: TSR (Tool Success Rate), TCRR (Tool-
    Call Redundancy Rate), optimal-path ratio.

Three dimensions produce a 0-100 score each. Composite uses the GEOMETRIC
MEAN so a zero on any dimension tanks the overall — explicit anti-Goodhart
vs. weighted-sum arithmetic mean (which would let Speed mask a bad Safety
score).

Dimensions (what we can observe today from Receipt events):

  * Throughput — volume of shipped work
      signals: files_changed, output_tokens, tool diversity
      skipped for v0: PR merged (no git integration yet), acceptance proxy
      (requires last-user-message sentiment classifier)

  * Reliability — how smoothly the run went
      signals: Tool Success Rate (1 - error_events / tool_calls),
      session-end cleanliness, error burst ratio
      skipped: retry/rollback detection (requires pattern mining)

  * Safety — weighted severity of red flags
      signals: flag-weighted penalty (NOT binary — severities matter)
      hard cap: db_destructive → overall ≤ 50 even if other axes perfect

Intentionally NOT scored (documented anti-patterns from research):

  * Raw tokens count (Goodhart: agent bavarde → pump score)
  * Session duration (short session = often BETTER signal)
  * Cache-read ratio in efficiency (cache-read is a GOOD signal, not bad)
  * Cost absolute (depends on model; a Sonnet session that fixes 5 bugs
    is objectively better than an Opus session that writes a haiku)

Normalization: v0 uses fixed saturating anchors (conservative). Once we
have ≥30 days of population data we switch to per-user rolling percentile
or z-score — that's the right way (SPACE paper §4.2) but needs volume.

References:
  - DX Core 4: https://newsletter.getdx.com/p/introducing-the-dx-core-4
  - SPACE: https://queue.acm.org/detail.cfm?id=3454124
  - SWE-bench Verified: https://openai.com/index/introducing-swe-bench-verified/
  - TSR/TCRR metrics: https://www.arxiv.org/pdf/2510.18170
  - Anti-Goodhart in DevEx: https://jellyfish.co/blog/goodharts-law-in-software-engineering
"""
from __future__ import annotations

import math
from dataclasses import dataclass


# ── signal anchors ───────────────────────────────────────────────────────────
# "Full" result per signal. Saturating linear normalization below the anchor,
# clipped to 100 above. These get replaced by z-score on rolling populations
# once Receipt has enough data — fixed anchors is a v0 compromise.
_NORM_FILES = 15
_NORM_OUTPUT_TOK = 300_000
_NORM_TOOL_DIVERSITY = 6

# ── red-flag severity weights ────────────────────────────────────────────────
# Penalty subtracted from 100 on Safety axis. Severity-weighted (DX Core 4
# recommendation vs. binary flag lists). Sum of penalties clipped by compute.
_FLAG_WEIGHTS: dict[str, int] = {
    "db_destructive":     45,  # DROP/TRUNCATE/unscoped DELETE = worst
    "secret_aws":         30,
    "secret_stripe":      30,
    "secret_ssh_privkey": 30,
    "secret_jwt":         15,
    "shell_rm":           25,
    "env_mutation":       10,
    "migration_file":      5,
    "ci_config":           3,
}
_UNKNOWN_FLAG = 8

# Hard-cap flags — if present, overall score can't exceed this ceiling even
# if throughput/reliability are perfect. Audit-grade: critical events need
# attention regardless of "productivity" spin.
_HARD_CAPS: dict[str, int] = {
    "db_destructive": 50,
    "secret_aws":     55,
    "secret_stripe":  55,
    "secret_ssh_privkey": 55,
}


@dataclass
class SessionScore:
    overall: int             # 0-100 geometric mean of axes (capped per flags)
    throughput: int          # 0-100
    reliability: int         # 0-100
    safety: int              # 0-100
    grade: str               # A ≥ 85 · B ≥ 70 · C ≥ 55 · D ≥ 40 · F
    breakdown: dict          # transparent signal values (for tooltips)


def _clamp(n: float) -> int:
    return max(0, min(100, int(round(n))))


def _grade(overall: int) -> str:
    if overall >= 85: return "A"
    if overall >= 70: return "B"
    if overall >= 55: return "C"
    if overall >= 40: return "D"
    return "F"


def compute_score(
    files_count: int,
    tools_called: list[str],
    tokens_output: int,
    tool_call_count: int,
    error_count: int,
    flags: list[str],
) -> SessionScore:
    """Compute the 3-axis score + composite.

    Inputs are all derived from Session + Event data (see sessions_router).
    tool_call_count = events with kind in {tool_use, file_change}.
    error_count = events with kind=error (synthesized from tool_response).
    """
    # ── Throughput ──────────────────────────────────────────────────────
    # Three equal-weighted sub-signals; saturate then average. Output-tokens
    # is the single most-gameable signal (agent yak-shaving) — balanced by
    # the other two so alone it can't push the axis past ~33.
    unique_tools: set[str] = set()
    for t in tools_called or []:
        if not isinstance(t, str):
            continue
        unique_tools.add("MCP" if t.startswith("mcp__") else t)
    files_s = min(100.0, (max(files_count, 0) / _NORM_FILES) * 100)
    output_s = min(100.0, (max(tokens_output, 0) / _NORM_OUTPUT_TOK) * 100)
    diversity_s = min(100.0, (len(unique_tools) / _NORM_TOOL_DIVERSITY) * 100)
    throughput = _clamp((files_s + output_s + diversity_s) / 3)

    # ── Reliability ─────────────────────────────────────────────────────
    # TSR = Tool Success Rate. Paper arxiv 2510.18170 shows it's the top
    # predictor of agent trajectory quality. Perfect run = 1.0. We also
    # bake in an absolute-errors penalty so a 1000-call session with
    # 50 errors (still 95% TSR) doesn't look as clean as a 20-call one
    # with zero errors.
    if tool_call_count > 0:
        tsr = max(0.0, 1.0 - error_count / max(tool_call_count, 1))
    else:
        # No tool calls = no failures, but also no work → neutral 50
        # rather than 100 (honest: we can't tell from nothing).
        tsr = 0.5
    absolute_penalty = min(30, error_count * 3)  # caps at 30 points lost
    reliability = _clamp(tsr * 100 - absolute_penalty)

    # ── Safety ──────────────────────────────────────────────────────────
    # Severity-weighted penalty. Unknown flags get a conservative mid weight.
    penalty = 0
    seen_flags: set[str] = set()
    for f in flags or []:
        if not isinstance(f, str) or f in seen_flags:
            continue
        seen_flags.add(f)
        penalty += _FLAG_WEIGHTS.get(f, _UNKNOWN_FLAG)
    safety = _clamp(100 - penalty)

    # ── Composite ───────────────────────────────────────────────────────
    # Geometric mean across the three axes. Small-number zero-protection
    # via +1 offset (math.prod on (0, x, y) = 0 which hard-zeroes composite
    # — desired most of the time, but we still want to differentiate a
    # 0/50/50 session from a 0/0/0 one). Using +1 then -1 keeps ordering
    # while avoiding the total-zero trap.
    axes = [throughput, reliability, safety]
    product = 1.0
    for a in axes:
        product *= (a + 1)
    composite = product ** (1 / len(axes)) - 1

    # Hard cap based on critical flags.
    ceiling = 100
    for f in seen_flags:
        if f in _HARD_CAPS:
            ceiling = min(ceiling, _HARD_CAPS[f])

    overall = _clamp(min(composite, ceiling))

    return SessionScore(
        overall=overall,
        throughput=throughput,
        reliability=reliability,
        safety=safety,
        grade=_grade(overall),
        breakdown={
            "files_count": files_count,
            "unique_tools": sorted(unique_tools),
            "output_tokens": tokens_output,
            "tool_calls": tool_call_count,
            "errors": error_count,
            "tool_success_rate": round(
                ((1 - error_count / tool_call_count) * 100) if tool_call_count else 0, 1
            ),
            "flag_penalty": penalty,
            "hard_ceiling": ceiling if ceiling < 100 else None,
            # Anchors — documented for auditors reading the number.
            "norms": {
                "files": _NORM_FILES,
                "output_tokens": _NORM_OUTPUT_TOK,
                "tool_diversity": _NORM_TOOL_DIVERSITY,
            },
        },
    )
