# Drain the Ready column — grouped, conflict-aware

Autonomously work through the **Ready** column for one component: fix every ticket, drive it to
all-green (local tests + CI), and merge it. **Unlike a strict one-at-a-time loop, first analyse the
Ready tickets, group entangled ones so they share a single branch + PR, and order the groups to
avoid conflicts** — then fix group by group. Independent tickets are simply groups of one.

**Why grouped:** branching every ticket from `main` in isolation thrashes when tickets overlap —
shared files, or a helper produced by one ticket and consumed by another. Separate PRs then collide
or duplicate work. Grouping coupled tickets into one logical PR, ordered foundation-first,
eliminates that.

**Scope guard:** `$ARGUMENTS` names the component; default `file-manager`. Only that component's
items in **Ready**. Never touch another component's tickets.

Identifiers come from `board-config.md` in this directory. Repeated here because this command is
run unattended:

- Project `PVT_kwHOAdChXs4BiTFK` · Status field `PVTSSF_lAHOAdChXs4BiTFKzhhLpVA`
- Status options — Backlog `0dced654`, Prioritized `3bef32f5`, Ready `c2fe13d9`, In Progress `d62b377d`, Completed `1f45fcd1`
- Priority field `PVTSSF_lAHOAdChXs4BiTFKzhhLvZo` — p1 `ead3a951`, p2 `3fc82bbd`, p3 `42e8e40a`, p4 `be83ec7b`, p5 `3ab5822a`

## Step 1 — Enumerate the Ready queue

**Filter at the source — never scan the whole board.** Board **Status** *is* available through
`gh issue list` on gh 2.45.0, so this needs no GraphQL:

```bash
LABEL="component:${1:-file-manager}"
ready=$(gh issue list --repo JeffreyPeacock/SystemUtils \
  --label "$LABEL" --state open --limit 100 \
  --json number,projectItems \
  --jq '.[] | select(any(.projectItems[]?; .status.name == "Ready")) | .number' | sort -n)
rc=$?
```

**Distinguish "no Ready tickets" from "the query did not run."** They look identical — both give an
empty string — and treating a failure as an empty queue reports success for work never done:

```bash
if [ $rc -ne 0 ]; then
    echo "CANNOT CHECK: gh issue list failed (rc=$rc). Not proceeding."; exit 1
fi
if [ -z "$ready" ]; then
    # Prove the query can return anything at all before believing the silence.
    total=$(gh issue list --repo JeffreyPeacock/SystemUtils --label "$LABEL" \
              --state open --limit 100 --json number --jq 'length')
    echo "Ready queue is empty for $LABEL ($total open in other columns)."; exit 0
fi
```

> **Do not reach for Priority or Area in this query.** `projectItems` carries only `status` and
> `title` — both come back `null` without erroring, which silently ranks every ticket the same.
> Priority needs the GraphQL project query in `/priority-review`; fetch it there if you need it for
> ordering (Step 2).

## Step 2 — Analyse and group (the smart pass)

Read each Ready ticket:

```bash
gh issue view <N> --repo JeffreyPeacock/SystemUtils --json title,body,labels
```

For each, extract:

- the **files and functions** it will touch — FileManager is a flat module layer, so "which file" is rarely enough; `src/db.py` alone is 223 statements and two tickets can sit in it without touching
- any **cross-references** to other tickets ("Related: #N", "Fix with #N", "Depends on #N")
- whether it **produces** something shared (a fixture, a helper, a renamed function) that another ticket **consumes**

Build an overlap graph and form **groups**:

- Same group when separating them would **conflict** (both edit the same function or region), **duplicate** work (both add the same helper), or when one **depends on** another's output.
- Otherwise **solo** — a group of one.
- **Guardrail — do not over-group.** Choose the *smallest* grouping that removes the conflict. A group must still be a coherent, reviewable PR; never merge unrelated tickets just because both are Ready. When in doubt, keep them separate.

**Worked example, from this repo's actual queue.** #1 (`remove-record`'s regex is prefix-anchored)
and #2 (`audit-db` has no dry-run) are both `Ready`, both p2, and both live in `src/db.py`. They are
**not** one group: #1 edits `remove_records_by_regex`, #2 edits `audit_db`, and the two functions do
not touch. Same file is not the test — same *region* is.

By contrast #1 and #7 (two different `remove_record` functions, and the CLI uses the one its help
does not describe) **are** one group whenever both are Ready: #7 renames the very function #1
rewrites, so separating them guarantees a conflict and #1's own body says "Fix with #7".

**Order** the groups topologically: foundational changes first, their consumers after. Break ties by
**Priority** (p1 before p5), then by lowest issue number. Priority is not in the Step 1 output — pull
it with the GraphQL query from `/priority-review` if the tie matters, and say so rather than
silently ordering by number alone.

## Step 3 — State the plan and start work. Do not ask for approval.

**This command runs unattended. There is no confirmation pause.** Invoking `/fix-ready` *is* the
approval: ordering the tickets and grouping them is the job being delegated, not a question to hand
back. Announce the ordered groups — for each: member tickets, the single PR it will produce
(`Closes #…`), the files and functions it touches, and *why* those tickets are grouped or kept
apart — then go straight into Step 4 in the same turn.

**Decide the judgement calls inside a ticket yourself**, and say in the PR body which way you went
and why. A ticket that leaves a choice open ("decide whether the flag means *at least N copies* or
*N beyond the first*") is asking the implementer to choose. Choose the reading that keeps existing
behaviour intact where one does, state it, and move on.

**Stop and ask only for a genuinely serious reason** — the kind where proceeding either way risks
real damage or wastes the work outright:

- a ticket's required change would delete or rewrite user data, or break the database format
- two Ready tickets specify contradictory behaviour, so satisfying one violates the other
- the fix needs a credential, a permission, or an external service that is not available
- a `CANNOT CHECK`: a gate could not be run, so "passing" cannot be distinguished from "not run"

Everything short of that — which grouping, which order, which name, which of two defensible
semantics — is decided and reported, never escalated.

## Step 4 — For each group G, in order

### 4a — Branch once from a fresh `main`

```bash
git checkout main && git pull --ff-only
git checkout -b file-manager/<group-desc>
```

Always cut from an up-to-date `origin/main`. Because group N+1 branches only *after* group N has
merged, cross-group conflicts are eliminated.

### 4b — Move members to In Progress

For each member ticket — targeted item-ID lookup, never a board scan:

```bash
ITEM_ID=$(gh api graphql -f query='{ repository(owner:"JeffreyPeacock",name:"SystemUtils"){ issue(number:N){ projectItems(first:5){ nodes{ id project{ number } } } } } }' \
  --jq '.data.repository.issue.projectItems.nodes[] | select(.project.number==14) | .id')
[ -n "$ITEM_ID" ] || { echo "CANNOT SET #N — no board item found"; exit 1; }
gh api graphql -f query='mutation { updateProjectV2ItemFieldValue(input: { projectId:"PVT_kwHOAdChXs4BiTFK" itemId:"'"$ITEM_ID"'" fieldId:"PVTSSF_lAHOAdChXs4BiTFKzhhLpVA" value:{ singleSelectOptionId:"d62b377d" } }) { projectV2Item { id } } }'
```

**Read the value back before believing it moved** — a mutation that returns an id has not been shown
to have changed anything.

### 4c — Implement all member tickets on the one branch

Address every member ticket's acceptance criteria on this single branch. Reuse the shared artifact
across members. Keep each ticket's tests with its code. For a group of one this is identical to the
per-ticket flow — you may invoke `/fix-ticket <N>` for solo groups if convenient; for multi-ticket
groups, implement directly so they share the branch.

**A bug fixed without a test that would have caught it is not finished** — see
`docs/Development-Principles.md` §3. Several Ready tickets have a `dup_tree` fixture available
(#12); use it rather than building state by hand.

### 4d — Gate locally

From `FileManager/`:

```bash
python -m pytest        # coverage on, floor enforced
python -m mypy src/     # must be clean
```

Both must pass for the whole group.

**Then check the ratchets, in the same PR:**

- If coverage rose a whole point or more above `--cov-fail-under` in `pytest.ini`, raise the floor.
- If a module became fully annotated, delete its opt-out stanza from `mypy.ini`.

Neither is ever lowered to make a red build green (`docs/Development-Principles.md` §4).

**If a ticket is pinned by a strict `xfail`, fixing it turns that test into an `XPASS` failure.**
That is the mechanism working — remove the `xfail` marker in the same commit as the fix. #5 is
currently pinned this way.

### 4e — One PR for the group

Commit, push, and open a **single** PR whose body lists `Closes #A`, `Closes #B`, … for **every**
member ticket, plus a short per-ticket summary. No AI attribution, no `Co-Authored-By`. Then
`git checkout main`.

```bash
gh pr list --repo JeffreyPeacock/SystemUtils --head file-manager/<group-desc> --json number --jq '.[0].number'
```

### 4f — Drive CI green

Poll the PR checks; on failure read the failing job, fix on the same branch, re-run `pytest` and
`mypy`, push, re-poll. **Up to 3 fix iterations.**

```bash
gh pr view <PR> --repo JeffreyPeacock/SystemUtils --json statusCheckRollup
```

A check that is `COMPLETED/SUCCESS` is green. Anything still `IN_PROGRESS` is **not** green and is
also not a failure — wait, do not merge, and do not report it either way.

### 4g — Merge

When local and CI checks are all green, merge via `/merge-pr <PR>`. It moves **every** closed issue
to Completed, deletes the branch, pulls `main`, updates the docs and regenerates the priority review.

**A multi-`Closes` PR needs no special handling, but note how the issues are found:** `/merge-pr`
parses closing keywords out of the PR body, because gh 2.45.0 rejects
`--json closingIssuesReferences` outright. So every member ticket must appear as its own
`Closes #N` line in the body — a bare `#N` mention will not close it.

### 4h — On unfixable group failure → split, then skip

If the group is still red after 3 iterations:

1. **Split** — fall back to the per-ticket flow for the group's members (`/fix-ticket <N>` one at a time, each branched from a fresh `main` after the previous merges) to isolate the offender.
2. If a specific ticket is still unfixable, blocked, or needs a human decision: comment on it describing what was attempted and why it is blocked; convert its PR to draft (`gh pr ready --undo <PR> --repo JeffreyPeacock/SystemUtils`); move it back to **Backlog** (option `0dced654`); note it and **continue** with the next group.

**Never merge a red PR**, and never report a group as done because the checks could not be read —
that is a `CANNOT CHECK`, which stops the run.

## Step 5 — Report

Summarise:

- the groups planned, with the rationale for each grouping **and each deliberate non-grouping**
- **every judgement call made inside a ticket** — the semantics chosen, the name picked, the
  alternative rejected — since no one was asked at the time
- PRs merged (PR # → issues closed)
- ratchet changes (coverage floor raised to N, mypy stanzas removed)
- any tickets split out or skipped, with the reason
- the final Ready-queue state — empty unless items were skipped
