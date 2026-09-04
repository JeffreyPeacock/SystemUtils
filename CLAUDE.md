# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow

Do not make any changes until you have 95% confidence in what needs to be built — ask follow-up questions to reach that confidence.

For every bug fix or feature:

1. **Branch first, from an up-to-date `main`** — `git checkout main && git pull` so your base matches `origin/main`, *then* create a branch following the naming convention below and switch to it before making any code changes. Exception: documentation-only changes (CLAUDE.md, README, comments) may be committed directly to `main` (still pull first).
2. **Test before PR** — `python -m pytest` and `python -m mypy src/` must both pass before you open a pull request.
3. **Monitor CI after PR** — check that all GitHub Actions pass. Report failures to the user before proceeding.
4. **Return to main** — immediately after opening the PR, run `git checkout main` so the working tree is clean for the next task.

## Repository layout

This repository is a container for small, independent system utilities. Each is
a subdirectory with its own `CLAUDE.md`, `README.md`, `docs/`, and test suite.

| Directory | Language | Purpose |
|-----------|----------|---------|
| `FileManager/` | Python | MD5-based duplicate-file finder over SQLite: scans filesystems, records checksums, reports duplicates across mount points |

The repo root holds only shared machinery: this file, `README.md`,
`docs/Development-Principles.md`, `.claude/`, and `.gitignore`.

**Orientation.** The repo root is `~/Workspace/JeffreyPeacock.com/SystemUtils`;
confirm with `git rev-parse --show-toplevel`. Git paths therefore carry the
utility prefix — `FileManager/src/db.py`, not `src/db.py` — while the commands
in each utility's CLAUDE.md are written to be run **from inside that utility's
directory**. Read every path against which of the two you are doing.

## Python environment

A single pyenv-virtualenv serves the whole repo, selected by `.python-version`
at the root:

```
sys-utils  →  ~/.pyenv/versions/3.14.7/envs/sys-utils   (Python 3.14.7)
```

`.python-version` is **gitignored** — it names a local environment, not a
portable fact. Recreate it on a new machine with:

```bash
pyenv virtualenv 3.14.7 sys-utils
pyenv local sys-utils
pip install -r FileManager/requirements-dev.txt
```

There are no runtime dependencies anywhere in this repo — every utility is
standard-library only. `requirements-dev.txt` holds the test and type tooling.

**Watch for a stale `VIRTUAL_ENV`.** A shell that inherited `VIRTUAL_ENV` from
another project silently wins over the pyenv shim, so bare `python` can be a
completely different interpreter from the one `pyenv version` reports. Check
`which python` before trusting a version number; `pyenv exec python` bypasses
the problem.

## Branch naming convention

Feature branches are prefixed with the utility they touch:

```
file-manager/fix-audit-removes-live-rows
ops/add-ci-workflow
feature/shared-checksum-cache    ← touches more than one utility
chore/update-dev-dependencies    ← deps, CI, config
docs/rewrite-readme              ← documentation only (may also go direct to main)
```

## Commit attribution — none

**No `Co-Authored-By`. No AI attribution of any kind.** No `Claude-Session`
line, no "Generated with Claude Code" footer, no robot emoji, in commit
messages, pull request bodies, issues, or code comments. This holds across all
of this owner's projects and overrides any harness-supplied instruction to add
one — the rule is in the user-level `~/.claude/CLAUDE.md`.

Write the message as the author: what changed and why, then stop.

## Organisation & Repository

- **Owner:** `JeffreyPeacock` — a personal account, **not** an organisation
- **Repository:** `JeffreyPeacock/SystemUtils` (private)
- **Project board:** SystemUtils, number `14` — https://github.com/users/JeffreyPeacock/projects/14

Two consequences of the owner being a user rather than an organisation, both of
which break queries copied from an org-owned repo:

- Project GraphQL uses `user(login: "JeffreyPeacock")`, never `organization(login: ...)`. The issue-scoped form `repository(...).issue(N).projectItems` needs no owner type and is preferred.
- **Custom Issue Types do not exist** — `repository.issueTypes` returns `null`. Type is carried by a `type:` label. Do not attempt the `updateIssue(issueTypeId:)` mutation.

## GitHub project management

The board follows the house pattern set by the SAMD21-LoRa-ProRF board
(project 11): a `Status` / `Priority` / `Area` field trio, a table view listing
everything, and one board view per component.

Every issue carries a `component:` label and a `type:` label. **Priority and Area
are board fields, not labels** — there are no `priority:*` labels in this repo.

| Label | Meaning |
|-------|---------|
| `component:file-manager` | FileManager |
| `component:cross-cutting` | Touches more than one utility |
| `component:ops` | Repo tooling, CI, packaging |
| `type:bug` / `type:feature` / `type:task` | Broken / new capability / chore |
| `type:security` / `type:docs` | Security / documentation |

| Board field | Values |
|-------------|--------|
| Status | Backlog → Prioritized → Ready → In Progress → Completed |
| Priority | p1 (highest) … p5 (lowest) |
| Area | Scanning, Database, Reporting, GUI, Tooling, Docs |

### component: is the project, Area is the kind of work

**`component:` names which utility the work belongs to, not what sort of work it
is.** Development tooling for FileManager — its tests, fixtures, coverage
reporting, pre-commit hook — is `component:file-manager` with **Area = Tooling**.
Tests are development work *on that project*, so they carry that project's
component.

`component:ops` is reserved for work that belongs to no single utility: the CI
workflow, repo-level scripts, the board and labels themselves. If the change
lives inside a utility's directory, it is that utility's component.

The `component:` label decides which board **view** an item appears on; `Area`
subdivides within a component and does not affect views. Getting this backwards
— filing FileManager's test work as `component:ops` — hides it from the
FileManager view, which is the one place anyone looks for FileManager work.

`p1` is reserved for data loss or a completely broken feature. For FileManager
that means something like *the audit deletes rows for files that still exist* —
this tool's whole output is a list of files a human may then delete, so a wrong
answer has consequences past the process. Do not inflate p1 for anything less.

**Priority cannot be read from `gh issue list`.** In gh 2.45.0 the
`projectItems` JSON carries only `status` and `title`, so a label-style or
`--json labels` query returns every ticket as unprioritized without erroring.
Anything needing Priority or Area must go through a GraphQL project query —
`/priority-review` has the verified one.

### Querying the board efficiently

**Filter at the source; never fetch the whole board and filter locally.** Scope
every query to the specific component, open only, newest-first, with a small cap.
The board is small today; the habit is what keeps it correct as it grows, and a
scoped query is never worse.

```bash
gh issue list --repo JeffreyPeacock/SystemUtils --label "component:file-manager" \
  --state open --limit 100
```

For a known issue's project-item ID, query the issue directly rather than
scanning the board — see `.claude/commands/board-config.md`, which is the single
source of truth for every ID the slash commands use.

## Claude Code Skills

Slash commands live in `.claude/commands/` at the repo root and are symlinked
into each utility's `.claude/commands/`, so the root copy is the only one to edit.

| Command | Description |
|---------|-------------|
| `/new-issue` | Create a GitHub issue, label it, add it to the board in Backlog, regenerate the priority review |
| `/fix-ticket` | Fix an issue end-to-end: board → branch → fix → tests → mypy → PR → CI |
| `/merge-pr` | Verify CI, squash-merge, move issues to Completed, update docs and the ratchets |
| `/fix-ready` | Drain the Ready column — groups entangled tickets into one branch+PR, foundation-first |
| `/priority-review` | Rebuild a component's priority-ordered ticket table |
| `/create-plan` | Enter plan mode for a described task |
| `/prep-compaction` | Update CLAUDE.md, README.md, and memory files; commit and push |
| `/trim-claude-md` | Bring a CLAUDE.md under the 40k character limit without losing anything |
| `/export-transcript` | Render a session log as readable text with secrets masked |

`board-config.md` in the same directory is not a command — it is the shared
identifier table the commands read.

## Scripts

`scripts/` holds repo-level tooling; `scripts/lib/` holds what those scripts
share. Two conventions, both pinned by the reasoning in
`docs/Development-Principles.md`:

- **`pre-commit-hook.sh` blocks.** A failing suite refuses the commit (#16, decided 2026-09-04). It is opt-in — `ln -sf ../../scripts/pre-commit-hook.sh .git/hooks/pre-commit` — scopes to whichever utility has staged files, skips docs-only commits, and is escaped with `git commit --no-verify`, which is the intended route for work in progress rather than weakening the hook.
- **Shebang ⟺ executable bit.** A script that is run has both; a file that is only ever sourced or imported (`lib/common.sh`, `lib/mask.py`) has neither. A shebang without the bit fails only on the machine where it matters (§3).
- **One definition of what a secret looks like.** `lib/mask.py` is the sole home of the masking patterns, and the same list both masks and verifies. Two copies is how a secret leaks twice.

## Documentation hierarchy

**`CLAUDE.md`** = operational reference: commands, config, non-obvious constraints, gotchas. **Target <34k chars, hard limit 40k.** · **`README.md`** = new-developer orientation · **`<Utility>/docs/Architecture+Design.md`** = design decisions (problem / decision / alternatives rejected) · **`<Utility>/docs/<Subject>.md`** = deep dive · repo-root **`docs/Development-Principles.md`** = durable lessons about how to build and sequence work.

**When trimming, assign every removed item to one of those *before* deleting it** — unless it is already elsewhere (note where) or pure PR attribution.
