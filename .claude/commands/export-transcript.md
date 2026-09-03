# Export this session's transcript

Render a Claude Code session log as readable text with secrets masked, using
`scripts/export-transcript.sh`.

`$ARGUMENTS` may contain a date, a session UUID, a utility name, or an output
path. Parse what is there and ask only for what is genuinely ambiguous.

## Run it

```bash
./scripts/export-transcript.sh
```

That exports the **most recent** session in the whole repository to
`.claude_artifacts/transcripts/YYYY.MM.DD-transcript.txt`, masking as it goes.
The whole of `.claude_artifacts/` is gitignored, and the script refuses to write
anywhere inside the repository that is not ignored.

Useful variants:

```bash
./scripts/export-transcript.sh --list                  # what sessions exist
./scripts/export-transcript.sh --scope FileManager     # only that utility's sessions
./scripts/export-transcript.sh --session <uuid>        # a specific one
./scripts/export-transcript.sh --out /tmp/t.txt        # somewhere else
./scripts/export-transcript.sh --no-thinking           # drop reasoning blocks
```

## This is a container repo, so sessions live in more than one place

Claude Code keys its log directory on the directory the session was **started
in**, encoding it by replacing `/` and `.` with `-`. A session started in
`SystemUtils` and one started in `SystemUtils/FileManager` therefore land in two
different directories under `~/.claude/projects/`.

The script searches the repo root and every immediate subdirectory, so
`--list` shows all of them with the originating directory in the last column.
Do not assume a single log directory — that assumption is why the upstream
version needed adapting.

## Masking is the point — do not casually disable it

**This project's sensitive material is not the reference project's.** That one
was a GPS receiver, and its rules were about location.

Here the transcript is largely **file paths and MD5 checksums**, and those are
the content — masking them would leave an unreadable file. What actually
identifies a person is narrower, so `scripts/lib/mask.py` masks:

| | |
|---|---|
| `home-user` | the **username segment only** of `/home/<user>/` or `/Users/<user>/`, so the tree structure survives and the person does not |
| `email` | any address |
| `coordinates` | a decimal-degree pair — a photo archive's directory names can carry one |
| `street-address` | an address as an order confirmation writes it |
| `token`, `private-key` | generic credential shapes, in case one ever appears |

It deliberately does **not** mask checksums, file sizes, mtimes, or the non-home
part of any path. Over-masking a log until it is unreadable defeats the
exercise.

Add a project-specific literal — an exact string no pattern will catch — to
`.claude_artifacts/mask-secrets.txt`, one per line. Prefer that over `--secret`,
which puts the value in shell history *and* in the next transcript.

## The verification is not decoration

`mask()` and `residual()` share one pattern list, deliberately. The script
re-scans its own output with the same patterns and **exits 3** if anything still
matches, and the wrapper turns that into a hard failure. If the two lists ever
drift apart the check becomes theatre, so never define a pattern anywhere but
`scripts/lib/mask.py`.

## Check the output before sharing it

```bash
grep -nE '/home/[a-z]|@[a-z-]+\.' <output>     # anything the patterns missed?
```

The scan only knows its own patterns. Skim the file.
