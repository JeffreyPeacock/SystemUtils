# Board configuration — SystemUtils

Single source of truth for every GitHub identifier the other commands use. When
any of these changes, change it **here** and update the commands that inline it.

| Item | Value |
|------|-------|
| Repo | `JeffreyPeacock/SystemUtils` (public) |
| Owner | `JeffreyPeacock` — a **user**, not an organisation |
| Project | **SystemUtils**, number `14` — https://github.com/users/JeffreyPeacock/projects/14 |
| Project ID | `PVT_kwHOAdChXs4BiTFK` |

The board mirrors the structure of the SAMD21-LoRa-ProRF board (project 11),
which is the house pattern: a `Status` / `Priority` / `Area` field trio, a table
view listing everything, and one board view per component.

## Fields

**Status** — `PVTSSF_lAHOAdChXs4BiTFKzhhLpVA`

| Column | Option ID | Meaning |
|--------|-----------|---------|
| Backlog | `0dced654` | Filed, not yet triaged |
| Prioritized | `3bef32f5` | Triaged and ranked |
| Ready | `c2fe13d9` | Specified and ready to start |
| In Progress | `d62b377d` | Branch open |
| Completed | `1f45fcd1` | Merged |

**Priority** — `PVTSSF_lAHOAdChXs4BiTFKzhhLvZo`

| Value | Option ID | Meaning |
|-------|-----------|---------|
| p1 | `ead3a951` | Highest — data loss or a feature completely broken |
| p2 | `3fc82bbd` | High — major impairment, no acceptable workaround |
| p3 | `42e8e40a` | Medium — impaired but a workaround exists |
| p4 | `be83ec7b` | Low — minor, cosmetic, rarely hit |
| p5 | `3ab5822a` | Lowest — enhancement or deferred |

**Area** — `PVTSSF_lAHOAdChXs4BiTFKzhhLvZs`

| Value | Option ID | Covers |
|-------|-----------|--------|
| Scanning | `d82f5544` | Directory walking, hashing, the skip check |
| Database | `4aa27676` | Schema, queries, SQLite locking |
| Reporting | `4a6c3afd` | Duplicate and size reports |
| GUI | `1eddb0a2` | The Tkinter duplicate browser |
| Tooling | `0a403536` | Scripts, CI, build, dev environment |
| Docs | `f578e119` | Documentation and findings |

## Priority is a board field, not a label

**There are no `priority:pN` labels in this repo** — the earlier WTIS-derived
setup used them and they were removed. Priority lives in the board's `Priority`
field, matching project 11. Two consequences:

- Setting a priority is a `updateProjectV2ItemFieldValue` mutation against the Priority field ID, not `gh issue edit --add-label`.
- **A priority cannot be read from `gh issue list --json labels`.** It comes from `projectItems[].fieldValues`, so any query that needs priority has to ask the board for it. `/priority-review` does exactly that.

Setting a single-select field value, for any of the three:

```bash
gh api graphql -f query='
mutation {
  updateProjectV2ItemFieldValue(input: {
    projectId: "PVT_kwHOAdChXs4BiTFK"
    itemId:    "<item-id>"
    fieldId:   "<field-id from the tables above>"
    value: { singleSelectOptionId: "<option-id>" }
  }) { projectV2Item { id } }
}'
```

## The owner is a user, not an organisation

This is the one difference that breaks a copied WTIS query. Project lookups go
through `user(login: "JeffreyPeacock")`, **not** `organization(login: ...)`.
Issue-scoped lookups (`repository(...).issue(N).projectItems`) are identical
either way and are the preferred form — they need no owner type at all.

## There are no custom Issue Types

Custom Issue Types (Bug / Feature / Task as a first-class field) are an
organisation feature. `repository.issueTypes` returns `null` here. Type is
carried by a **label**:

| Type | Label |
|------|-------|
| Bug | `type:bug` |
| Feature | `type:feature` |
| Chore, maintenance, refactor | `type:task` |
| Security | `type:security` |
| Documentation | `type:docs` |

## Components

| Component | Label | Docs directory |
|-----------|-------|----------------|
| FileManager | `component:file-manager` | `FileManager/docs` |
| Touches more than one utility | `component:cross-cutting` | *(unmapped — ask)* |
| Repo tooling, CI, packaging | `component:ops` | *(unmapped — ask)* |

The board's per-component views filter on these labels
(`label:component:file-manager`), so the label is what puts an issue on the
right view — the `Area` field subdivides *within* a component and does not
affect which view an item appears on.

## Views

| # | Name | Layout | Filter |
|---|------|--------|--------|
| 1 | ListView | Table | *(none — everything)* |
| 2 | FileManager | Board | `label:component:file-manager` |

Add one board view per new utility, filtered by its `component:` label.

## Querying

Scope every query at the source — never fetch the whole board and filter locally:

```bash
gh issue list --repo JeffreyPeacock/SystemUtils --label "component:file-manager" \
  --state open --limit 100
```
