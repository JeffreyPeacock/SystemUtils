# File Manager — Ticket Priority Review

The SystemUtils project board (#14) on GitHub holds the authoritative detail; this doc is the
at-a-glance ordering view the board doesn't give cleanly.

**Snapshot:** 2026-11-21 20:16 MST · 2 open · 2 Backlog

|  Pri   | #  |  Status |   Area   | Title | Note |
|:------:|:--:|:-------:|:--------:|-------|------|
| **p4** | 53 | Backlog |   GUI    | New utility: a GUI duplicate browser and editor,<br>separate from the CLI scanner | Carries the decision from #11 — the requirements<br>gap was resolved by making the GUI its own<br>application rather than revising the requirement.<br>Carries the defect from #3 as well: the old GUI<br>wrote `PY_VAR3`, the checkbox object, not a path,<br>so its `rm_commands.txt` was never runnable. Build<br>the path logic outside the widget tree this time.<br>Still needs a name and its own `component:` label. |
| **p4** | 68 | Backlog | Database | verify-db loads every recorded row before hashing:<br>peak memory scales with the database | The counterpart to #67 in `verify-db` (#50):<br>`recorded_checksums` materialises every row before<br>the first file is hashed — measured<br>**~253 bytes per row**, so<br>**~1.31 GiB for /home2**. Less urgent than the<br>number looks, because `/home2` is btrfs with scrub<br>and the volume that actually needs an<br>application-level verify is the ext4 `BACKUP/00` at<br>~0.25 GiB; `--prefix` also bounds a run today. The<br>constraint on fixing it is that `with_connection`<br>closes the connection before returning, so no<br>generator may outlive it — keyset pagination on<br>`path` fits the existing `ORDER BY` and would make<br>a verify restartable, which #50 deferred. |

## Tally

| Priority | p1 | p2 | p3 | p4 | p5 | — | Total |
|----------|---:|---:|---:|---:|---:|--:|------:|
| Open | 0 | 0 | 0 | 2 | 0 | 0 | 2 |

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
