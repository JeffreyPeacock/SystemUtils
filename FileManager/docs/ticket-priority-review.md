# File Manager — Ticket Priority Review

The SystemUtils project board (#14) on GitHub holds the authoritative detail; this doc is the
at-a-glance ordering view the board doesn't give cleanly.

**Snapshot:** 2026-11-19 16:27 MST · 4 open · 4 Backlog

|  Pri   | #  |  Status |   Area   | Title | Note |
|:------:|:--:|:-------:|:--------:|-------|------|
| **p3** | 75 | Backlog | Scanning | scan hangs if the producer thread raises: no<br>sentinels are put, and a finally-block fix would<br>hide the failure | Found while fixing #67. Not likely today, because<br>`os.walk` drops directory errors, but if the<br>producer raises before its sentinels, every worker<br>waits in `queue.get()` forever and an unattended<br>scan hangs without an error. Putting the sentinels<br>in `finally` alone would turn the hang into a<br>partial index reported as complete with exit 0,<br>which is the problem #57 fixed. The failure must<br>also be recorded in the tally and exit 3. |
| **p4** | 53 | Backlog |   GUI    | New utility: a GUI duplicate browser and editor,<br>separate from the CLI scanner | Carries the decision from #11 — the requirements<br>gap was resolved by making the GUI its own<br>application rather than revising the requirement.<br>Carries the defect from #3 as well: the old GUI<br>wrote `PY_VAR3`, the checkbox object, not a path,<br>so its `rm_commands.txt` was never runnable. Build<br>the path logic outside the widget tree this time.<br>Still needs a name and its own `component:` label. |
| **p4** | 68 | Backlog | Database | verify-db loads every recorded row before hashing:<br>peak memory scales with the database | The counterpart to #67 in `verify-db` (#50):<br>`recorded_checksums` materialises every row before<br>the first file is hashed — measured<br>**~253 bytes per row**, so<br>**~1.31 GiB for /home2**. Less urgent than the<br>number looks, because `/home2` is btrfs with scrub<br>and the volume that actually needs an<br>application-level verify is the ext4 `BACKUP/00` at<br>~0.25 GiB; `--prefix` also bounds a run today. The<br>constraint on fixing it is that `with_connection`<br>closes the connection before returning, so no<br>generator may outlive it — keyset pagination on<br>`path` fits the existing `ORDER BY` and would make<br>a verify restartable, which #50 deferred. |
| **p4** | 69 | Backlog | Database | A missing database directory exits 1 with a<br>traceback, and 1 means "invalid argument" | `mkdir -p /var/lib/filemanager` is currently an<br>undocumented prerequisite: without it the run<br>prints its header and then dies with an uncaught<br>`sqlite3.OperationalError` and a six-frame<br>traceback from inside the zipapp.<br>**It exits 1, which the contract defines as "a required argument was missing or invalid"**<br>— the argument was fine. The 1 is Python's default<br>for an uncaught exception, not a decision. It fails<br>before any hashing, so nothing is wasted. The<br>ticket's open decision is which code to use;<br>whatever is chosen goes in `usage()`, `main()`'s<br>docstring and the README table in the same change.<br>Must not create the directory silently. |

## Tally

| Priority | p1 | p2 | p3 | p4 | p5 | — | Total |
|----------|---:|---:|---:|---:|---:|--:|------:|
| Open | 0 | 0 | 1 | 3 | 0 | 0 | 4 |

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
