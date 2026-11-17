# File Manager — Ticket Priority Review

The SystemUtils project board (#14) on GitHub holds the authoritative detail; this doc is the
at-a-glance ordering view the board doesn't give cleanly.

**Snapshot:** 2026-11-16 18:18 MST · 3 open · 2 Prioritized, 1 Backlog

|  Pri   | #  |    Status   |   Area   | Title | Note |
|:------:|:--:|:-----------:|:--------:|-------|------|
| **p2** | 50 | Prioritized | Scanning | No way to verify stored checksums: scan and<br>audit-db both skip on (size, mtime) and miss<br>corruption | The read-back half of the integrity problem: the<br>baseline is recorded correctly and nothing ever<br>checks it. `/home2` is btrfs, which already<br>checksums data and is scrubbed, so the real case is<br>the ext4 backup volume. Pairs with #57 — a gap in<br>the index and an unverified index fail the same<br>way. |
| **p2** | 54 | Prioritized | Tooling  | FileManager: ship a single zipapp executable<br>(dist/filemanager.pyz) for root-run unattended<br>scans | Requirements 1-5, 8 and 11 are done: 1-5 and 8 in<br>#52/PR #55, and 11 split out as #57 and merged in<br>PR #59. 6 rejected, 7 relaxed. What is left is<br>`--version` carrying the build commit, which gates<br>the Desktop-Ops installer; a timestamped header<br>with the zone; and the rest of the artifact test.<br>The title still says `filemanager.pyz`; the<br>artifact is `FileManager.pyz`. |
| **p4** | 53 |   Backlog   |   GUI    | New utility: a GUI duplicate browser and editor,<br>separate from the CLI scanner | Carries the decision from #11 — the requirements<br>gap was resolved by making the GUI its own<br>application rather than revising the requirement.<br>Carries the defect from #3 as well: the old GUI<br>wrote `PY_VAR3`, the checkbox object, not a path,<br>so its `rm_commands.txt` was never runnable. Build<br>the path logic outside the widget tree this time.<br>Still needs a name and its own `component:` label. |

## Tally

| Priority | p1 | p2 | p3 | p4 | p5 | — | Total |
|----------|---:|---:|---:|---:|---:|--:|------:|
| Open | 0 | 2 | 0 | 1 | 0 | 0 | 3 |

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
