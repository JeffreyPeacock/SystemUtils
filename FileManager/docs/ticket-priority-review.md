# File Manager — Ticket Priority Review

The SystemUtils project board (#14) on GitHub holds the authoritative detail; this doc is the
at-a-glance ordering view the board doesn't give cleanly.

**Snapshot:** 2026-09-04 18:42 MST · 3 open · all in Backlog

|  Pri   | #  |  Status |   Area   | Title | Note |
|:------:|:--:|:-------:|:--------:|-------|------|
| **p2** | 41 | Backlog | Scanning | is_file_unique reports an unreadable file as a<br>duplicate, not as unknown | Filed out of #33's coverage work. `False` means<br>"not unique", so a read error and a real duplicate<br>give the same answer, and the file drops out of the<br>keep list. Current behaviour is pinned by a test,<br>so this is a contract change. |
| **p4** | 3  | Backlog |   GUI    | The GUI writes the checkbox object, not the path,<br>so rm_commands.txt is not runnable | The GUI's only output is unrunnable — it writes<br>`PY_VAR3`, not a path. Extract the path logic out<br>of the widget while fixing, which also serves #15. |
| **p4** | 11 | Backlog |   GUI    | The GUI is a paginated duplicate list, not the file<br>manager the requirements describe | The largest requirements gap, and a decision rather<br>than a defect. Decide whether to build it or revise<br>the requirement. |

## Tally

| Priority | p1 | p2 | p3 | p4 | p5 | — | Total |
|----------|---:|---:|---:|---:|---:|--:|------:|
| Open | 0 | 1 | 0 | 2 | 0 | 0 | 3 |

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
