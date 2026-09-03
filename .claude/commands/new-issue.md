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
- Any priority — `p1`–`p5`, or words like "critical"/"high"/"medium"/"low"/"trivial" → map to the matching `priority:pN` label
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

Every issue gets exactly one `priority:pN` label. If `$ARGUMENTS` specifies a priority, use it; otherwise infer from the issue's impact using the rubric below, and surface your choice in the Step 1 confirmation so the user can correct it. When genuinely unsure, default to `priority:p3` and say so.

| Label | Meaning |
|-------|---------|
| `priority:p1` | Critical — data loss, or a feature completely broken; fix immediately |
| `priority:p2` | High — major functionality impaired, no acceptable workaround |
| `priority:p3` | Medium — feature impaired but a workaround exists; schedule soon |
| `priority:p4` | Low — minor, cosmetic, or rarely hit; batch when convenient |
| `priority:p5` | Trivial — enhancement, barely noticeable, or deferred |

`p1` is reserved for genuine data-loss situations — do **not** inflate it. This
tool deletes files and rewrites a database of checksums, so "p1" here means
something like *the audit removes rows for files that still exist*. Most new
tickets land at p3–p4.

## Steps

1. Confirm the parsed title, component, type, **priority**, and description with a brief summary before creating — one line is enough. If anything critical is missing, ask. Otherwise proceed without waiting.

2. Create the issue:
```bash
gh issue create --repo JeffreyPeacock/SystemUtils \
  --title "<title>" --body "<body>" \
  --label "<component:x>" --label "priority:pN" --label "<type:x>"
```
Body should include: what the problem or feature is, why it matters, and any acceptance criteria or implementation notes from `$ARGUMENTS`.

3. Add to the SystemUtils project:
```bash
gh project item-add 14 --owner JeffreyPeacock --url <issue-url>
```

4. Set status to **Backlog**. Get the item ID **directly for this issue** — never scan the board. Retry once after a short wait if it comes back empty (project-attachment lag):
```bash
gh api graphql -f query='
{ repository(owner:"JeffreyPeacock", name:"SystemUtils") {
    issue(number: <issue-number>) {
      projectItems(first: 5) { nodes { id project { number } } }
    } } }' \
  --jq '.data.repository.issue.projectItems.nodes[] | select(.project.number==14) | .id'
```
Then set status:
```bash
gh api graphql -f query='
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "PVT_kwHOAdChXs4BiTFK"
    itemId: "<item-id>"
    fieldId: "PVTSSF_lAHOAdChXs4BiTFKzhhLpVA"
    value: { singleSelectOptionId: "bdbd311d" }
  }) { projectV2Item { id } }
}'
```

5. **Regenerate the priority review for this component — required, not optional.**

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

6. Report: issue number, URL, component label, priority label, type label, confirmed added to the
   SystemUtils project in Backlog, **and the path of the priority review you regenerated** (or why it
   was skipped).
