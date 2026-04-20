# Contributing to Receipt

Thanks for your interest in Receipt.

## Project status

Receipt's v0 shipped autonomously; the codebase lands fast and ships
continuously. A formal open-source license has **not yet** been attached,
so this repo is currently in *watch-and-feedback* mode:

- **Issues** — welcome today. Bug reports, usability feedback, and
  feature requests are the best way to help while licensing is
  finalised.
- **Pull requests** — welcome as drafts for discussion. PRs will not be
  merged until a `LICENSE` file lands on `main`; an OSS announcement
  will follow in the repo `README.md` when that happens.

Small fixes (typos, broken links, obvious bugs) may be merged sooner on
a case-by-case basis.

## Before you open a pull request

1. Read [`ARCHITECTURE.md`](./ARCHITECTURE.md) so your change lands in
   the right layer (ingest, dashboard, or CLI).
2. Run the end-to-end smoke and make sure it still passes:
   ```bash
   bash scripts/smoke-us14.sh
   ```
   It installs the CLI, wires the Claude Code hook, posts sample
   events, and asserts the red-flag detector fired — all under 60
   seconds.
3. If you're changing behaviour, add a test. Backend tests live in
   `backend/apps/api/tests/`; run `cd backend && uv run pytest`.

## Commit and PR conventions

Commits follow a lightweight conventional style. Pick the prefix that
matches the primary intent of the change:

| Prefix      | When to use                              |
|-------------|------------------------------------------|
| `feat:`     | Adds user-visible behaviour              |
| `fix:`      | Fixes a bug                              |
| `docs:`     | Documentation-only change                |
| `chore:`    | Tooling, config, dependencies            |
| `refactor:` | Behaviour-preserving code reshape        |
| `test:`     | Adds or fixes tests                      |

Keep subject lines ≤72 characters, imperative mood, no trailing period.
One concern per PR beats a sprawling patch.

**Squash-merge is the default.** The squash commit message should
summarise the final landed change; work-in-progress commits don't need
to be tidy.

## Code of conduct

This project adopts the
[Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
By participating you agree to uphold it.

## Further reading

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — system topology and key
  decisions
- [`API.md`](./API.md) — HTTP reference
- [`DEVELOPMENT.md`](./DEVELOPMENT.md) — local setup and the
  edit-run-verify loop
