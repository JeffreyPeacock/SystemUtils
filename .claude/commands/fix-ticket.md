# Fix a GitHub issue end-to-end

Fix the issue number given in the argument (e.g. `/fix-ticket 12`). Follow every step in order.

Identifiers come from `board-config.md` in this directory.

## Determine the issue number

The issue number is the argument passed to this skill. If no argument was provided, ask the user for it and stop.

## Step 0 — Move ticket to In Progress

Look up the project item ID **directly for this issue** — never scan the board:

```bash
ITEM_ID=$(gh api graphql -f query='
{ repository(owner:"JeffreyPeacock", name:"SystemUtils") {
    issue(number: <issue-number>) {
      projectItems(first: 5) { nodes { id project { number } } }
    } } }' \
  --jq '.data.repository.issue.projectItems.nodes[] | select(.project.number==14) | .id')
```

If `ITEM_ID` is empty (brief propagation lag for a freshly added item), wait a few seconds and retry once.

Then set its status to In Progress:

```bash
gh api graphql -f query='
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "PVT_kwHOAdChXs4BiTFK"
    itemId: "<item-id>"
    fieldId: "PVTSSF_lAHOAdChXs4BiTFKzhhLpVA"
    value: { singleSelectOptionId: "d62b377d" }
  }) { projectV2Item { id } }
}'
```

If the item is not found in the project, warn the user and continue — the board is optional; the fix is not.

## Step 1 — Read the issue

```bash
gh issue view <N> --repo JeffreyPeacock/SystemUtils --json number,title,body,labels
```

Read the issue body carefully. Identify:
- Which utility is affected (from the `component:` label or issue body)
- Which files are likely involved
- What the expected behaviour is and what is currently broken

Do not make any changes until you have 95% confidence in what needs to be built. Ask the user follow-up questions if you are not there yet.

## Step 2 — Check the current branch

```bash
git branch --show-current
```

You must be on `main` before creating a feature branch. If you are not on `main`, run `git checkout main && git pull` first.

## Step 3 — Create a branch

Use the branch naming convention from the repo-root CLAUDE.md:

```
file-manager/fix-<short-description>
ops/fix-<short-description>
feature/<short-description>   ← touches more than one utility
chore/<short-description>     ← deps, CI, config
```

```bash
git checkout -b <branch-name>
```

## Step 4 — Read relevant files

Read the source files identified in Step 1 before editing anything. Use the Read tool, not cat.

## Step 5 — Implement the fix

Make the minimum change required to fix the issue. Do not add features, refactor, or clean up unrelated code.

## Step 6 — Run the test suite

From `FileManager/`:

```bash
python -m pytest
```

`pytest.ini` turns on coverage and enforces the floor, so a passing run also
proves coverage did not regress. All tests must pass before proceeding.

**If your change raised coverage, raise the floor in the same PR.** The
`--cov-fail-under` value in `pytest.ini` is a ratchet toward the 95% that
`FileManager/docs/REQUIREMENTS.txt` demands — it only ever goes up. Set it to the new whole
number at or just below what the run reports.

## Step 7 — Run mypy

```bash
python -m mypy src/
```

Must report `Success: no issues found` before proceeding.

**If you annotated a module fully, remove its opt-out stanza from `mypy.ini`** in
the same PR. A module graduates to strict checking by being annotated, never by
the defaults being loosened.

## Step 8 — Commit

Stage only the files you changed:

```bash
git add <specific files>
git commit -m "Fix: <description> (#<N>)"
```

No `Co-Authored-By`, no `Claude-Session` line, no AI attribution of any kind —
see the repo-root CLAUDE.md. Write the message as the author.

## Step 9 — Push and open a PR

```bash
git push -u origin <branch-name>
```

```bash
gh pr create --repo JeffreyPeacock/SystemUtils \
  --title "Fix: <description> (#<N>)" \
  --body "$(cat <<'BODY'
## Summary
- <bullet points describing what changed and why>

## Test plan
- [ ] `python -m pytest` passes, coverage floor holds
- [ ] `python -m mypy src/` clean
- [ ] <any manual steps specific to this fix>

Closes #<N>
BODY
)"
```

## Step 10 — Return to main

```bash
git checkout main
```

## Step 11 — Monitor CI

```bash
gh pr view <PR> --repo JeffreyPeacock/SystemUtils --json statusCheckRollup
```

Report any failures to the user before they merge.
