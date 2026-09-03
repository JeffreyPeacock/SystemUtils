Create a new GitHub issue in `JeffreyPeacock/SystemUtils` and add it to the SystemUtils project board.

Identifiers come from `board-config.md` in this directory — read it rather than
re-deriving them.

Parse as much as possible from `$ARGUMENTS` (free-form text is fine — title, component, type, notes). Only ask for what is genuinely missing.

## Defaults

- **Component** defaults to `component:file-manager` unless overridden in `$ARGUMENTS` or by context — it is the only utility in the repo today
- **Type** has no default — infer from context or ask

## Parsing $ARGUMENTS

Extract from the arguments string:
- Anything that looks like a title (a phrase describing the issue)
- Any `component:xxx` or component name ("file manager", "ops", "cross-cutting") → map to the correct label
- Any `type:xxx` or type name ("bug", "chore", "feature") → map to the matching `type:` label
- Any priority — `p1`–`p5`, or words like "critical"/"high"/"medium"/"low"/"trivial" → map to the matching **Priority field** value (not a label; see below)
- Any remaining text → use as description / notes for the issue body

## Component labels

| Name | Label |
|------|-------|
| FileManager (default) | `component:file-manager` |
| Touches more than one utility | `component:cross-cutting` |
| Repo tooling, CI, packaging | `component:ops` |

## Type labels

This repo is user-owned, so GitHub's custom **Issue Types** do not exist here —
`repository.issueTypes` returns `null`. Type is a label, always:

| Name | Label |
|------|-------|
| Bug | `type:bug` |
| Feature | `type:feature` |
| Chore / maintenance / refactor | `type:task` |
| Security | `type:security` |
| Documentation | `type:docs` |

Do **not** attempt the `updateIssue(issueTypeId:)` GraphQL mutation — it fails on
this repo. That step exists in the WTIS version of this command and does not
carry over.

## Priority

Every issue gets exactly one priority. **It is a board field, not a label** — there are no `priority:*` labels in this repo. If `$ARGUMENTS` specifies a priority, use it; otherwise infer from the issue's impact using the rubric below, and surface your choice in the Step 1 confirmation so the user can correct it. When genuinely unsure, default to `p3` and say so.

| Value | Meaning |
|-------|---------|
| **p1** | Critical — data loss, or a feature completely broken; fix immediately |
| **p2** | High — major functionality impaired, no acceptable workaround |
| **p3** | Medium — feature impaired but a workaround exists; schedule soon |
| **p4** | Low — minor, cosmetic, or rarely hit; batch when convenient |
| **p5** | Trivial — enhancement, barely noticeable, or deferred |

`p1` is reserved for genuine data-loss situations — do **not** inflate it. This
tool deletes files and rewrites a database of checksums, so "p1" here means
something like *the audit removes rows for files that still exist*. Most new
tickets land at p3–p4.

## Steps

1. Confirm the parsed title, component, type, **priority**, and description with a brief summary before creating — one line is enough. If anything critical is missing, ask. Otherwise proceed without waiting.

2. Create the issue (priority is **not** a label — it is set on the board in step 5):
```bash
gh issue create --repo JeffreyPeacock/SystemUtils \
  --title "<title>" --body "<body>" \
  --label "<component:x>" --label "<type:x>"
```
Body should include: what the problem or feature is, why it matters, and any acceptance criteria or implementation notes from `$ARGUMENTS`.

3. Add to the SystemUtils project:
```bash
gh project item-add 14 --owner JeffreyPeacock --url <issue-url>
```

4. Get the project item ID **directly for this issue** — never scan the board. Retry once after a short wait if it comes back empty (project-attachment lag):
```bash
ITEM_ID=$(gh api graphql -f query='
{ repository(owner:"JeffreyPeacock", name:"SystemUtils") {
    issue(number: <issue-number>) {
      projectItems(first: 5) { nodes { id project { number } } }
    } } }' \
  --jq '.data.repository.issue.projectItems.nodes[] | select(.project.number==14) | .id')
```

5. Set **Status = Backlog**, **Priority**, and **Area** on that item. Three mutations against the same item, one per field — IDs from `board-config.md`:
```bash
set_field() {   # set_field <field-id> <option-id>
  gh api graphql -f query="
  mutation {
    updateProjectV2ItemFieldValue(input: {
      projectId: \"PVT_kwHOAdChXs4BiTFK\"
      itemId:    \"$ITEM_ID\"
      fieldId:   \"$1\"
      value: { singleSelectOptionId: \"$2\" }
    }) { projectV2Item { id } }
  }" --jq '.data.updateProjectV2ItemFieldValue.projectV2Item.id'
}

set_field PVTSSF_lAHOAdChXs4BiTFKzhhLpVA 0dced654    # Status   = Backlog
set_field PVTSSF_lAHOAdChXs4BiTFKzhhLvZo <p1..p5>    # Priority
set_field PVTSSF_lAHOAdChXs4BiTFKzhhLvZs <area>      # Area
```

Priority option IDs: p1 `ead3a951` · p2 `3fc82bbd` · p3 `42e8e40a` · p4 `be83ec7b` · p5 `3ab5822a`
Area option IDs: Scanning `d82f5544` · Database `4aa27676` · Reporting `4a6c3afd` · GUI `1eddb0a2` · Tooling `0a403536` · Docs `f578e119`

Infer the **Area** from what the issue touches and state your choice in the step 1 confirmation alongside the priority. If it genuinely spans several, leave Area unset rather than guessing.

6. **Regenerate the priority review for this component — required, not optional.**

   The user works from the component's `ticket-priority-review.md` in an open editor tab, not from
   chat output. A ticket that is not in that file is, in practice, a ticket they cannot see.

   Run the `/priority-review` procedure for the component this issue was filed under (see
   `priority-review.md` for the full spec — do not re-derive the query). Rules specific to this step:

   - **Write the Note for the ticket you just filed.** Do not leave it blank. You have the rationale
     in context right now — one short line on why it matters or what it blocks — and you will never
     have it that cheaply again. Blank Notes are for tickets filed by someone else.
   - **Preserve every existing Note verbatim** for tickets that are still open. Never regenerate or
     reword a human-written Note.
   - Update the `**Snapshot:**` line with a fresh local-time timestamp (`date +'%Y-%m-%d %H:%M %Z'`)
     and the new open count / status mix.
   - **Component with no mapped doc path** (`cross-cutting`, `ops`): there is no per-component review
     file. Say so in the report and skip — do not invent a path.
   - Do **not** commit the file. It is committed per the docs workflow when the user asks.

7. Report: issue number, URL, component label, type label, Priority and Area set on the board, confirmed added to the
   SystemUtils project in Backlog, **and the path of the priority review you regenerated** (or why it
   was skipped).
