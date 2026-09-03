Verify CI, squash-merge a PR, and complete all post-merge housekeeping.

Identifiers come from `board-config.md` in this directory.

## Determine the PR

If `$ARGUMENTS` contains a PR number, use it. Otherwise infer from the current branch:
```bash
gh pr view --json number,title,body,statusCheckRollup,closingIssuesReferences
```
If no PR is found, report and stop.

## Step 1 — Verify CI

```bash
gh pr view <PR> --json statusCheckRollup
```
- Any check **pending**: report which are still running and stop. Do not merge.
- Any check **failed**: report which failed and stop. Do not merge.
- All **SUCCESS** (or no checks configured): proceed.

## Step 2 — Squash and merge

```bash
gh pr merge <PR> --squash --delete-branch
```

If the merge fails for any reason, report and stop. Do not proceed with housekeeping on a failed merge.

## Step 3 — Pull main

```bash
git checkout main && git pull
```

## Step 4 — Identify closed issues

Parse the PR body and title for closing keywords (`closes`, `fixes`, `resolves`) followed by `#<number>`. Also read `closingIssuesReferences` from the PR JSON fetched in Step 1. Collect all unique issue numbers.

## Step 5 — Move issues to Done on the board

For each closed issue number, get the project item ID **directly for this issue** — never scan the board:
```bash
gh api graphql -f query='
{ repository(owner:"JeffreyPeacock", name:"SystemUtils") {
    issue(number: <issue-number>) {
      projectItems(first: 5) { nodes { id project { number } } }
    } } }' \
  --jq '.data.repository.issue.projectItems.nodes[] | select(.project.number==14) | .id'
```

Set status to Done:
```bash
gh api graphql -f query='
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "PVT_kwHOAdChXs4BiTFK"
    itemId: "<item-id>"
    fieldId: "PVTSSF_lAHOAdChXs4BiTFKzhhLpVA"
    value: { singleSelectOptionId: "c96d5cd3" }
  }) { projectV2Item { id } }
}'
```

## Step 6 — Remove closed issues from CLAUDE.md and README.md

For each closed issue, find its entry in the utility's `CLAUDE.md` and `README.md` and **delete the line entirely**. Closed issues live in GitHub (the Done column) — the backlog should contain only open work.

Read both files first, make targeted edits only. Do not rewrite unaffected sections. If removing an entry leaves a section header with no remaining items, remove the header too.

## Step 7 — Update the Architecture+Design record if needed

Check whether any closed issue has a `## Design Decision` section in its body, or whether the PR implemented an approach that was non-obvious or chosen over alternatives.

If yes, add a narrative entry to `FileManager/docs/Architecture+Design.md`:
- Open with the problem being solved
- State the decision and why it was chosen
- Note what was ruled out, if applicable
- End with `**Related issues:** #N`
- Separate entries with `---`

If no design decision is involved, skip this step.

## Step 8 — Check the ratchets

Two values in the merged code are floors that only move up. Confirm the merge did not leave them stale:

```bash
cd FileManager && python -m pytest 2>&1 | tail -3
```

If the reported coverage now exceeds the `--cov-fail-under` in `pytest.ini` by a
whole point or more, raise the floor and include it in the Step 10 docs commit.
Likewise, if every opt-out module in `mypy.ini` is now annotated, remove the
stanza.

## Step 9 — Update memory

Read `MEMORY.md` to find the relevant memory files, then update the ones affected by this merge — closed issues, current branch state, any convention this PR established.

Do NOT commit memory files — they are local only.

## Step 10 — Commit and push docs

```bash
git add FileManager/CLAUDE.md FileManager/README.md
git commit -m "Docs: mark #<N> done (PR #<PR>)"
git push
```

If multiple issues were closed, list them all: `"Docs: mark #X, #Y done (PR #<PR>)"`.

Include `FileManager/docs/Architecture+Design.md`, `FileManager/pytest.ini`, or `FileManager/mypy.ini` in the same commit if Steps 7 or 8 changed them.

## Step 11 — Regenerate the priority review — required, not optional

Closing tickets changes the review just as much as filing them does. A merged ticket still sitting in the review is the same failure as a new ticket missing from it, in the opposite direction.

Run the `/priority-review` procedure for the component of each closed issue (see `priority-review.md` — do not re-derive the query). Rules specific to this step:

- **Drop the merged tickets** and refresh the `**Snapshot:**` line (fresh local-time timestamp via `date +'%Y-%m-%d %H:%M %Z'`, new open count, new status mix) and the `## Tally` row. Verify the per-priority counts against the live board rather than decrementing by hand.
- **Preserve every remaining Note verbatim.** Never regenerate or reword a human-written Note.
- If a merged ticket's Note recorded something still true of the code — a sequencing constraint, a correction to another ticket's body — carry that fact onto the ticket it now applies to rather than deleting it with the row.
- Components with no mapped doc path (`cross-cutting`, `ops`) have no review file: say so and skip, never invent a path.
- Commit the review **with** the docs commit in Step 10 (`git add FileManager/docs/ticket-priority-review.md`) — unlike `/new-issue`, this command already commits, so the review rides along.

## Step 12 — Report

Summarise:
- PR merged and branch deleted
- Issues closed and moved to Done on the board
- CLAUDE.md / README.md updated
- Coverage floor / mypy stanzas adjusted, or confirmed still correct
- Memory updated
- **Priority review regenerated** — path, and the open count before → after
- Any items that could not be found or updated, so the user can fix them manually
