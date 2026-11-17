# File Manager — Ticket Priority Review

The SystemUtils project board (#14) on GitHub holds the authoritative detail; this doc is the
at-a-glance ordering view the board doesn't give cleanly.

**Snapshot:** 2026-11-17 13:18 MST · 4 open · 3 Ready, 1 Backlog

|  Pri   | #  |  Status |   Area   | Title | Note |
|:------:|:--:|:-------:|:--------:|-------|------|
| **p2** | 50 |  Ready  | Scanning | No way to verify stored checksums: scan and<br>audit-db both skip on (size, mtime) and miss<br>corruption | The read-back half of the integrity problem: the<br>baseline is recorded correctly and nothing ever<br>checks it. `/home2` is btrfs, which already<br>checksums data and is scrubbed, so the real case is<br>the ext4 backup volume. Pairs with #57 — a gap in<br>the index and an unverified index fail the same<br>way. |
| **p2** | 54 |  Ready  | Tooling  | FileManager: ship a single zipapp executable<br>(dist/FileManager.pyz) for root-run unattended<br>scans | What is left after #62: a timestamped header with<br>the zone (requirement 10) and the rest of the<br>artifact test (requirement 12). Requirements 1-5<br>and 8 landed in #52/PR #55, 11 as #57, and<br>**9 as #62 — so the Desktop-Ops installer's gate is cleared**;<br>they can install rather than only run from the<br>repo. 6 rejected, 7 relaxed. The artifact is<br>`FileManager.pyz`: the owner renamed it 2026-11-16<br>and the title, requirement 2 and the acceptance<br>checks were corrected to match on 2026-11-17, with<br>Desktop-Ops agreeing. |
| **p4** | 53 | Backlog |   GUI    | New utility: a GUI duplicate browser and editor,<br>separate from the CLI scanner | Carries the decision from #11 — the requirements<br>gap was resolved by making the GUI its own<br>application rather than revising the requirement.<br>Carries the defect from #3 as well: the old GUI<br>wrote `PY_VAR3`, the checkbox object, not a path,<br>so its `rm_commands.txt` was never runnable. Build<br>the path logic outside the widget tree this time.<br>Still needs a name and its own `component:` label. |
| **p4** | 60 |  Ready  | Tooling  | audit_db's counts dict is heterogeneous: typed as<br>dict[str, Any] behind a mypy opt-out | Filed from the ratchet check while merging PR #59:<br>#57 had added `counts['failures']` to a dict mypy<br>infers as `dict[str, int]`, and the `src.db`<br>opt-out swallowed the error, so<br>`python -m mypy src/` stayed green. PR #61 restored<br>the documented two-literal state with<br>`dict[str, Any]`. The real fix is a `TypedDict`,<br>which also unblocks typing `src.main` — that module<br>passes today only because `audit_db` returns `Any`<br>out of an unchecked one. Changes the return<br>contract and its three callers. |

## Tally

| Priority | p1 | p2 | p3 | p4 | p5 | — | Total |
|----------|---:|---:|---:|---:|---:|--:|------:|
| Open | 0 | 2 | 0 | 2 | 0 | 0 | 4 |

&nbsp;

**Legend** — what each priority means:

| Pri | Meaning |  | Pri | Meaning |
|-----|---------|---|-----|---------|
| **p1** | Critical — data loss or a feature completely broken; fix now |  | **p4** | Low — minor / cosmetic / rarely hit; batch when convenient |
| **p2** | High — major impairment, no acceptable workaround |  | **p5** | Trivial — enhancement / deferred / no current impact |
| **p3** | Medium — impaired but a workaround exists; schedule soon |  |  |  |

## Refresh

```bash
LABEL="component:file-manager"
gh api graphql -f query='
query($num:Int!) { user(login:"JeffreyPeacock") { projectV2(number:$num) {
  items(first:100) { nodes {
    content { __typename
      ... on Issue { number title state labels(first:20){nodes{name}} } }
    fieldValues(first:20) { nodes {
      ... on ProjectV2ItemFieldSingleSelectValue {
        name field { ... on ProjectV2SingleSelectField { name } } } } }
} } } } }' -F num=14 --jq '
.data.user.projectV2.items.nodes[]
| select(.content.__typename=="Issue" and .content.state=="OPEN")
| select([.content.labels.nodes[].name] | index("'"$LABEL"'"))
| (.fieldValues.nodes) as $fv
| ( [ $fv[] | select(.field.name=="Priority") | .name ][0] // "p9" ) as $pri
| ( [ $fv[] | select(.field.name=="Status")   | .name ][0] // "--" ) as $st
| ( [ $fv[] | select(.field.name=="Area")     | .name ][0] // "--" ) as $area
| select($st != "Completed")
| [$pri, (.content.number|tostring), $st, $area, .content.title] | @tsv' \
| LC_ALL=C sort -t$'\t' -k1,1 -k2,2n
```

Or run `/priority-review file-manager`, which regenerates this file and preserves
every Note.
