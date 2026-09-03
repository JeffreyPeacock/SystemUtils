# Board configuration — SystemUtils

Single source of truth for every GitHub identifier the other commands use. When
any of these changes, change it **here** and update the commands that inline it.

| Item | Value |
|------|-------|
| Repo | `JeffreyPeacock/SystemUtils` |
| Owner | `JeffreyPeacock` — a **user**, not an organisation |
| Project | **SystemUtils**, number `14` — https://github.com/users/JeffreyPeacock/projects/14 |
| Project ID | `PVT_kwHOAdChXs4BiTFK` |
| Status field ID | `PVTSSF_lAHOAdChXs4BiTFKzhhLpVA` |

Status option IDs:

| Column | Option ID | Meaning |
|--------|-----------|---------|
| Backlog | `bdbd311d` | Filed, not yet scheduled |
| Ready | `aa397369` | Specified and ready to start |
| In Progress | `69fccd20` | Branch open |
| In Review | `323087dc` | PR open, awaiting CI and review |
| Done | `c96d5cd3` | Merged |

## The owner is a user, not an organisation

This is the one difference that breaks a copied WTIS query. Project lookups go
through `user(login: "JeffreyPeacock")`, **not** `organization(login: ...)`.
Issue-scoped lookups (`repository(...).issue(N).projectItems`) are identical
either way and are the preferred form — they need no owner type at all.

## There are no custom Issue Types

Custom Issue Types (Bug / Feature / Task as a first-class field) are an
organisation feature. `repository.issueTypes` returns `null` here. Type is
carried by a **label** instead:

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
| FileManager | `component:file-manager` | `FileManager/doc` |
| Touches more than one utility | `component:cross-cutting` | *(unmapped — ask)* |
| Repo tooling, CI, packaging | `component:ops` | *(unmapped — ask)* |

## Querying

The board is small today, but query it scoped anyway — the habit is what keeps
it correct as it grows, and a scoped query is never worse:

```bash
gh issue list --repo JeffreyPeacock/SystemUtils --label "component:file-manager" \
  --state open --limit 100
```

Never `gh project item-list` the whole board and filter locally.
