# File Manager — Ticket Priority Review

The SystemUtils project board (#14) on GitHub holds the authoritative detail; this doc is the
at-a-glance ordering view the board doesn't give cleanly.

**Snapshot:** 2026-09-03 16:28 MST · 15 open · 13 Backlog, 2 Ready

|  Pri   | #  |  Status |    Area   | Title | Note |
|:------:|:--:|:-------:|:---------:|-------|------|
| **p2** | 1  |  Ready  |  Database | remove-record's regex is prefix-anchored and<br>unterminated, so it deletes siblings | Silent data loss. `re.match` anchors the start<br>only, so `/a/b` also removes `/a/bc`. Fix with #7 —<br>same function, same confusion. |
| **p2** | 2  |  Ready  |  Database | audit-db has no dry-run, so an unmounted volume<br>silently empties its rows | Silent data loss at volume scale. One failed mount<br>empties every row beneath it and there is no way to<br>preview a run. |
| **p3** | 3  | Backlog |    GUI    | The GUI writes the checkbox object, not the path,<br>so rm_commands.txt is not runnable | The GUI's only output is unrunnable — it writes<br>`PY_VAR3`, not a path. Extract the path logic out<br>of the widget while fixing, which also serves #15. |
| **p3** | 4  | Backlog | Reporting | report-duplicate-sizes halves the total, which is<br>only right for pairs | Understates by 25% at three copies, 40% at ten.<br>Correct only for pairs. The `dup_tree` fixture from<br>#12 now makes this cheap to test. |
| **p3** | 5  | Backlog | Reporting | Duplicate reporting splits GROUP_CONCAT on a comma,<br>tearing apart paths that contain one | Commas are legal and common in media filenames —<br>the stated use case. Groups silently report names<br>that do not exist. |
| **p3** | 8  | Backlog |  Tooling  | Raise coverage from 29.81% toward the 95% the<br>requirements ask for | The umbrella for the 29.81% → 95% gap. #12 landed<br>and unblocked it; still needs #13 for `main.py`.<br>Close only when the floor reaches 95. |
| **p3** | 9  | Backlog |  Tooling  | The fm-*.sh wrappers run an older copy of the<br>project | The scheduled scans do not run this code at all —<br>they `cd` to an older copy. Any fix landed here is<br>invisible to them. |
| **p3** | 13 | Backlog |  Tooling  | A fixture that invokes the CLI, so main.py can be<br>tested at all | `main.py` is 17% of `src/` statements and 9%<br>covered; 95% is arithmetically unreachable without<br>it. **Unblocked — #12 has landed.** |
| **p3** | 14 | Backlog |  Tooling  | Generate a per-file coverage summary on every test<br>run | Makes the gap legible per file — the total is the<br>one number that survives the scroll today. Ports<br>close to as-is. |
| **p4** | 6  | Backlog | Reporting | --min-duplicates is off by one | `HAVING COUNT(*) > ?` where the flag reads as "at<br>least". Decide the meaning first, then make help<br>and code agree. |
| **p4** | 7  | Backlog |  Database | Two different remove_record functions, and the CLI<br>uses the one its help does not describe | Two functions, one name, and `main.py` imports the<br>one its own help does not describe. Do with #1. |
| **p4** | 10 | Backlog |  Database | reporting.py opens its own SQLite connections<br>instead of going through db.py | No retry on the read path, so a report run during a<br>scan raises instead of waiting. Two places to<br>change whenever connection handling moves. |
| **p4** | 11 | Backlog |    GUI    | The GUI is a paginated duplicate list, not the file<br>manager the requirements describe | The largest requirements gap, and a decision rather<br>than a defect. Decide whether to build it or revise<br>the requirement. |
| **p4** | 15 | Backlog |  Tooling  | Annotate files that are intentionally below full<br>coverage | So `gui.py` at 9% reads as a deliberate boundary,<br>not neglect. Needs #14. Only claim "covered<br>elsewhere" where true. |
| **p4** | 16 | Backlog |  Tooling  | Decide whether a pre-commit hook blocks or warns,<br>then add it | **Blocked on your decision:** block or warn. CI<br>already gates every push, so this is feedback<br>speed, not the gate. Do not implement until<br>answered. |

## Tally

| Priority | p1 | p2 | p3 | p4 | p5 | — | Total |
|----------|---:|---:|---:|---:|---:|--:|------:|
| Open | 0 | 2 | 7 | 6 | 0 | 0 | 15 |

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
