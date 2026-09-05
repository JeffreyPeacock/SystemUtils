# File Manager — Ticket Priority Review

The SystemUtils project board (#14) on GitHub holds the authoritative detail; this doc is the
at-a-glance ordering view the board doesn't give cleanly.

**Snapshot:** 2026-09-04 17:22 MST · 8 open · all in Backlog

|  Pri   | #  |  Status |    Area   | Title | Note |
|:------:|:--:|:-------:|:---------:|-------|------|
| **p2** | 8  | Backlog |  Tooling  | Epic: raise coverage from 50.44% to the 95% the<br>requirements ask for | **Epic, not a unit of work — keep out of Ready.**<br>Children #32-#36; closes when the floor reaches 95.<br>Now at 50.44%. |
| **p2** | 32 | Backlog |  Scanning | Cover the scan engine: file_ops is at 35% | **Highest-value of the five.** The scan engine, and<br>the sentinel shutdown would *hang* rather than fail<br>if it regressed. |
| **p3** | 33 | Backlog |  Database | Cover db.py's retry loops and unique-file scan: 64% | The lock-retry loops are the entire concurrency<br>safety net and no test has ever entered one. Cover<br>the re-raise branch too. |
| **p3** | 34 | Backlog | Reporting | Cover the reporting actions: reporting.py is at 29% | Every action but one untested. #4 and #22 were<br>found only when a test finally reached them. |
| **p4** | 3  | Backlog |    GUI    | The GUI writes the checkbox object, not the path,<br>so rm_commands.txt is not runnable | The GUI's only output is unrunnable — it writes<br>`PY_VAR3`, not a path. Extract the path logic out<br>of the widget while fixing, which also serves #15. |
| **p4** | 11 | Backlog |    GUI    | The GUI is a paginated duplicate list, not the file<br>manager the requirements describe | The largest requirements gap, and a decision rather<br>than a defect. Decide whether to build it or revise<br>the requirement. |
| **p4** | 35 | Backlog |  Tooling  | Cover utils.py, including report_settings' untested<br>guard: 23% | Cheapest point on the board — 21 statements.<br>Includes `report_settings`, added by #2 with no<br>test of its own. |
| **p4** | 36 | Backlog |  Tooling  | Cover main.py's remaining dispatch arms: 80% | Dispatch arms #13's fixture does not reach. Assert<br>the `--use-gui` call, do not open a window. |

## Tally

| Priority | p1 | p2 | p3 | p4 | p5 | — | Total |
|----------|---:|---:|---:|---:|---:|--:|------:|
| Open | 0 | 2 | 2 | 4 | 0 | 0 | 8 |

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
