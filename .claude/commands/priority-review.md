# Rebuild a ticket-priority-review.md for a component

Generate (or refresh) a **priority-ordered quick-review table** of the open tickets for one
`component:` on the SystemUtils project board, and write it to that utility's docs directory. The
board holds the authoritative detail; this doc is the at-a-glance *ordering by priority* the board
doesn't give cleanly.

> **Adapted for SystemUtils** from the WTIS version. Two things carry over unchanged — priority
> lives in a **`priority:pN` label**, not a board field, and the board is queried **component-scoped
> via `gh issue list`**, never a `projectV2` scan. One thing differs: the owner is a **user**, so any
> project query that needs an owner uses `user(login:)`, not `organization(login:)`. Prefer the
> issue-scoped `repository(...).issue(N).projectItems` form, which needs neither.

## Inputs
- `$1` — **component** (required): `file-manager`, `cross-cutting`, `ops`, or a full
  `component:xxx`. Normalize: strip a leading `component:`, lowercase → `LABEL=component:<x>`.
  If `$1` is missing, default to `file-manager` — it is the only utility with a mapped path — and
  say that you did.
- `$2` — **output path** (optional): defaults to the mapped path below.

## Config
- Repo: `JeffreyPeacock/SystemUtils` · Owner: `JeffreyPeacock` (**user**) · Project number: `14`
- **Priority** comes from the `priority:pN` label; **Status** comes from the issue's board item
  (`projectItems[].status.name`).
- Component → output directory (default filename `ticket-priority-review.md`):

  | component | output dir |
  |---|---|
  | `file-manager` | `FileManager/doc` |
  | `cross-cutting` / `ops` / *(unmapped)* | ask for the path, or use `$2` |

## Priority rubric (include verbatim in the output — render as this 2-up table)

A 5-column table: priority+meaning in cols 1–2 (p1–p3) and cols 4–5 (p4–p5); col 3 is an empty spacer.

**Priority rubric**

| Pri | Meaning |  | Pri | Meaning |
|-----|---------|---|-----|---------|
| **p1** | Critical — data loss or a feature completely broken; fix now |  | **p4** | Low — minor / cosmetic / rarely hit; batch when convenient |
| **p2** | High — major impairment, no acceptable workaround |  | **p5** | Trivial — enhancement / deferred / no current impact |
| **p3** | Medium — impaired but a workaround exists; schedule soon |  |  |  |

## Steps

1. **Resolve inputs.** Normalize `$1` → `LABEL`. Resolve the output path (`$2` or the map). Ensure
   the target docs dir exists. Capture the **date and time** in the workstation's local timezone:
   `DATE=$(date +'%Y-%m-%d %H:%M %Z')`. **Run `date`; never write a timestamp by hand** — a
   hand-written one drifts from the real clock and has been written into the future more than once.
   Pass the captured value into whatever generates the file rather than retyping it. The timestamp —
   not just the date — is required so successive same-day rebuilds are distinguishable (local time,
   not UTC — this is a human-facing at-a-glance doc).

2. **Pull board data** — open issues for the component; Status from the board item; priority from the
   label (component-scoped, no full-board scan; `--jq` reads `$LABEL` from the env):
   ```bash
   gh issue list --repo JeffreyPeacock/SystemUtils --label "$LABEL" --state open --limit 200 \
     --json number,title,labels,projectItems \
     --jq '.[]
       | ((([.labels[].name]|map(select(startswith("priority:")))|.[0]) // "priority:p9") | ltrimstr("priority:")) as $pri
       | ((.projectItems[]? | select(.status!=null) | .status.name) // "--") as $st
       | select($st != "Done")
       | [$pri, (.number|tostring), $st, .title] | @tsv' \
     | LC_ALL=C sort -t$'\t' -k1,1 -k2,2n
   ```
   This yields rows `priority \t number \t status \t title`, sorted by priority then issue number.
   A ticket with **no `priority:pN` label** comes back as `p9` — it **sorts last**; render it as `—` in
   the table (and flag it: an unprioritized open ticket needs triage). `--state open` already drops
   closed issues; `select($st != "Done")` drops any still-open ticket parked in board-Done. If it
   returns nothing, report "no open `<LABEL>` tickets" and stop.

3. **Preserve human notes.** If the target file already exists, read it and extract the **Note**
   column (last cell) keyed by issue number. In the rebuilt table, reuse each existing note for any
   issue still present; leave the Note **blank** for issues new since last rebuild. Never discard a
   human-written note for a ticket that still exists. (Optionally offer to draft notes for the
   new/blank ones — one short rationale each — but only after writing the file.)

4. **Write the file** with the Write tool. Structure:
   - `# <Utility> — Ticket Priority Review` (title-case the component, e.g. `File Manager`)
   - One-line intro: "The SystemUtils project board (#14) on GitHub holds the authoritative detail;
     this doc is the at-a-glance ordering view the board doesn't give cleanly."
   - `**Snapshot:** <DATE> · <N> open · <status mix>` where `<DATE>` is the full local-time timestamp
     from Step 1 (e.g. `2026-09-02 20:41 MDT` — date **and** time), then `<status mix>` (e.g. "all in
     Backlog", or list the spread).
   - The ticket table — columns: `Pri | # | Status | Title | Note` — bolding the `pN` in the Pri
     column; render the `p9`/no-priority rows as `—`.
   - **The `#` column is a bare issue number — never a markdown link.** Write `| 12 |`, not
     `| [#12](https://github.com/JeffreyPeacock/SystemUtils/issues/12) |`. A linked cell carries ~60
     characters of URL, which blows out the `#` column, squeezes `Status` until "Backlog" wraps, and
     makes renderers shrink the whole table's font. The doc is read at a glance in an editor tab, so
     column width is the whole point. Issue numbers referenced **inside** the Note or in prose
     sections may be written `#12` (or linked, outside the table) — the rule is about the `#`
     column only.
   - Table format:

     ```
     |  Pri   |  #  | Status  | Title | Note |
     |:------:|:---:|:-------:|-------|------|
     | **p1** |  7  | Backlog | audit-db removes rows for files that still exist | ...
     ```

     - `Pri`, `#`, `Status`: padded to `(longest value + 2)`, content **centred** in the cell
       (`value.center(width)`), alignment colons in the separator.
     - `Title`, `Note`: one space each side, left ragged; separator is `len("Title")+2` / `len("Note")+2`.
     - Widths come from **this component's** content — `Status` may hold `In Progress` (11) where
       another only reaches `Ready` (7). Never copy another component's separator verbatim.

     **Wrap the two long columns with `<br>` so no cell is one unbroken run.** Insert a break at
     word boundaries every **51** characters in `Title` and `Note` (`WRAP = 51`). Never break inside a
     `` `code` `` span, `**bold**`, or a `[link](url)` — tokenise those as atomic before wrapping.

     Why: a markdown table is sized by its **total** content width, and once that exceeds the pane
     the renderer compresses columns proportionally, which starves the short ones until they wrap
     one character per line. The threshold measured in the reference project sits between 214 and
     259 characters of total width; the *ratio* between columns is not what matters, the total is.
     With `<br>` wrapping the effective total is about 112, since a wrapped cell is only as wide as
     its longest segment.

     **When regenerating, unwrap before re-wrapping.** Notes are read back out of the existing file
     and already contain `<br>`; replace those with a space before applying `wrap()` again, or the
     breaks compound and the column narrows on every rebuild.

   - A `## Tally` section: a count table `Priority | p1 | p2 | p3 | p4 | p5 | — | Total` with a single
     `Open` row; then a `&nbsp;` spacer line; then `**Legend** — what each priority means:` followed
     by the priority-rubric table (verbatim, above). The legend lives **here, beneath the tally** —
     it's the key that explains the p1–p5 codes. (`&nbsp;` paragraphs render as real vertical space;
     plain blank lines collapse.)
   - A `## Refresh` section embedding the Step-2 command so the doc is self-regenerating.

5. **Report:** path written, count per priority tier, and **list any new tickets** (blank Note) plus
   any **unprioritized** (`—`) tickets so the user knows what to annotate / triage. Do **not** commit —
   commit it per the docs workflow (docs → `main`) when the user asks.

## Notes
- Open-only by design (`--state open` + excludes board-`Done`). To include closed history, use
  `--state all` and drop the `select($st != "Done")` clause.
- Priority is read from the **`priority:pN` label**, not a board field — keep that in sync with the
  board (`/new-issue` and this command both treat the label as authoritative).
- The `Note`/rationale is **analysis**, not board data — it's the one column the board can't supply,
  which is why this skill preserves it across rebuilds rather than regenerating it blindly.
- Priorities themselves are assessed elsewhere; this skill only *renders* whatever labels the board
  currently holds.
