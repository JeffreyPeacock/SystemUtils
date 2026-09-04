# SystemUtils

Personal system utilities. Each subdirectory is an independent tool with its own
documentation, tests, and backlog; the repository root holds only the shared
conventions they are all built to.

| Utility | Language | What it does |
|---------|----------|--------------|
| [`FileManager/`](FileManager/) | Python | Walks filesystems, computes an MD5 per file into a SQLite database, and reports duplicates across separate mount points |

### Documentation map

| File | Purpose |
|------|---------|
| `README.md` (this file) | Orientation for the repository as a whole — setup, conventions, where things live |
| `CLAUDE.md` | Operational reference for Claude Code: workflow, branch naming, board configuration, gotchas |
| [`docs/Development-Principles.md`](docs/Development-Principles.md) | Durable lessons about how work is built and sequenced here — foundation-first prioritisation, recording a run's configuration, testing what review cannot see, and the quality ratchet |
| `<Utility>/README.md` | New-developer orientation for one utility |
| `<Utility>/CLAUDE.md` | Operational reference for one utility |
| `<Utility>/docs/Architecture+Design.md` | Design decision record: problem, decision, alternatives rejected |

---

## Setup

Python 3.14.7 through a pyenv-virtualenv shared by every utility in the repo:

```bash
pyenv virtualenv 3.14.7 sys-utils
pyenv local sys-utils
pip install -r FileManager/requirements-dev.txt
```

`pyenv local` writes `.python-version`, which is **gitignored** — it names an
environment on your machine, not a portable fact about the project.

There are no runtime dependencies. Every utility here is standard-library only;
`requirements-dev.txt` holds nothing but the test and type tooling (pytest,
pytest-cov, coverage, mypy).

### A trap worth knowing about

If your shell inherited `VIRTUAL_ENV` from another project, that virtualenv wins
over the pyenv shim and bare `python` is a different interpreter from the one
`pyenv version` names — with no warning. Check first:

```bash
which python          # should be under ~/.pyenv/
pyenv exec python -V  # bypasses the problem entirely
```

---

## Working here

```bash
git checkout main && git pull
git checkout -b file-manager/fix-something

cd FileManager
python -m pytest        # coverage is on by default and the floor is enforced
python -m mypy src/     # must be clean

git add <files> && git commit -m "Fix: ... (#N)"
git push -u origin file-manager/fix-something
gh pr create
git checkout main
```

Branch prefixes: `file-manager/`, `ops/`, `feature/` (more than one utility),
`chore/` (deps, CI, config), `docs/`. Documentation-only changes may go straight
to `main`.

### The pre-commit hook

Optional, and **it blocks**: a failing suite refuses the commit. Install it from
the repository root —

```bash
ln -sf ../../scripts/pre-commit-hook.sh .git/hooks/pre-commit
```

It runs `pytest` and `mypy` for whichever utility has staged changes, costs
about 2.3 seconds, skips documentation-only commits entirely, and does nothing
when a commit touches no utility. Because `pytest.ini` enforces the coverage
floor, a coverage regression fails it too — deliberately.

Work in progress is expected to need an escape hatch, and using it is normal:

```bash
git commit --no-verify
```

Remove the hook with `rm .git/hooks/pre-commit`. Note it tests the working
tree rather than the staged snapshot; the reasoning is in the script header.

### Quality ratchets

Two numbers in this repo only ever move up, and the reasoning is in
[Development-Principles §4](docs/Development-Principles.md):

- **`FileManager/pytest.ini` → `--cov-fail-under`.** Currently `29`, against a measured 29.81%. `FileManager/docs/REQUIREMENTS.txt` asks for 95%. Raise the floor in the same PR that raises real coverage.
- **`FileManager/mypy.ini` → the per-module opt-out stanzas.** A module leaves the list by being annotated, never by the defaults being loosened.

Neither is lowered to make a red build green.

---

## Issue tracking

Work is tracked on the **SystemUtils** board:
https://github.com/users/JeffreyPeacock/projects/14

It follows the same shape as the SAMD21-LoRa-ProRF board — a `Status` /
`Priority` / `Area` field trio, a `ListView` table showing everything, and one
board view per component.

| | |
|---|---|
| **Status** | Backlog → Prioritized → Ready → In Progress → Completed |
| **Priority** | p1 (highest) … p5 (lowest) |
| **Area** | Scanning, Database, Reporting, GUI, Tooling, Docs |
| **Labels** | a `component:` (which utility) and a `type:` (bug, feature, task, security, docs) |

Priority and Area are **board fields, not labels**. The `component:` label is
what places an issue on the right board view.

This repository is owned by a personal account rather than an organisation, so
GitHub's custom **Issue Types** are unavailable — type is a plain label, and
project GraphQL queries use `user(login:)`, not `organization(login:)`.

---

## Licence

MIT — see [LICENSE](LICENSE).

## Claude Code

Slash commands live in `.claude/commands/` at the repo root and are symlinked
into each utility, so the root copy is the only one to edit:
`/new-issue`, `/fix-ticket`, `/fix-ready`, `/merge-pr`, `/priority-review`,
`/create-plan`, `/prep-compaction`, `/trim-claude-md`, `/export-transcript`. Every GitHub identifier they use is
collected in `.claude/commands/board-config.md`.
