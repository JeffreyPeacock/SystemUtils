# FILEMANAGER(1)

> **Generated file — do not edit.** Rendered from
> [`man/filemanager.1`](filemanager.1) by `scripts/render_man.py`.
> Edit the troff source and regenerate; `tests/test_man_page.py`
> fails while this file disagrees with it.

*FileManager Manual · SystemUtils · 2026-11-19*

## NAME

filemanager - index files by MD5 checksum and report duplicates across filesystems

## SYNOPSIS

```
filemanager [--version] [--help]
filemanager action [path] [--db-path path] [--threads n] [--prefix prefix]
    [--exclude-prefix list] [--min-duplicates n] [--dirA path] [--dirB path]
    [--regex] [--dry-run] [--prune-missing-dirs]
```

## DESCRIPTION

**filemanager** walks one or more directory trees, computes an MD5 checksum for every
regular file it finds, and records (*md5sum*, *size*, *last_modified*, *path*) in a
SQLite database. The database is then queried to find files whose contents are
identical, including across separate filesystems and mount points, which is what
duplicate finders scoped to a single tree cannot do.

Its output is a list of files a human may then delete. A wrong answer therefore has
consequences past this process, and the program is built around that: a question it
cannot answer is reported as unanswered rather than guessed, and an action that
completed only partly says so in its exit status.

**Only regular files are read or recorded, and a symlink is never followed.** Every
other entry — a symlink, whatever it points at; a character or block device; a FIFO; a
socket — is skipped without being opened, logged as `NOT REGULAR (kind), skipped: path`,
and counted by kind for the run's summary. A skip is not a failure, because nothing that
belongs in the index was missed. A copy of */dev/random* never reaches end of file and a
FIFO blocks the **open**(2) until a writer appears, so reading either one made a scan
never finish. A root backup made with `rsync -a` recreates both, so any backup volume
can hold them (#74).

### The skip check

Rescanning a large tree is cheap because **scan** and **audit-db** read the stored
*size* and *last_modified* for each path and return without hashing when both still
match. *last_modified* is stored as integer milliseconds, `int(os.path.getmtime(path) *
1000)`.

The consequence matters when choosing an action: **the skip check is blind to any change
that does not alter size or mtime.** Bit rot, a bad sector, a failing cable and a
silently truncated copy all rewrite bytes without touching either, so those are exactly
the files **scan** skips. **verify-db**, and only **verify-db**, rehashes
unconditionally.

### Invocation

There are two supported forms, and they differ in which interpreter runs.

- **From a checkout**

  `python src/main.py` run from the *FileManager* directory. **src/main.py** prepends
  its parent to *sys.path* and every module imports its siblings as *src.\<module\>*, so
  running it from any other working directory breaks the imports.

- **From the bundle**

  `./FileManager.pyz`, a single-file Python **zipapp** archive built by
  *scripts/build-pyz.sh*. It pins `/usr/bin/python3 -I` in its shebang and depends on
  nothing outside the standard library, which is what makes it safe to run as another
  user.

**Do not run** `sudo python src/main.py`. **sudo**(8) resolves **python** from root's
*PATH*, not from the invoking user's **pyenv**(1) shim, so it silently selects a
different interpreter or none at all. Use the bundle for privileged runs. The name under
which the bundle is installed is the installer's choice; this page calls it
**filemanager**.

## ACTIONS

Exactly one action is required, as the first non-option argument. **scan**,
**check-file**, **scan-dir-report**, **remove-record** and **get-file-info** also
require *path*.

- **scan** *path*\[*,path...*\]

  Walk each directory or file in the comma-separated list and record a checksum for
  every regular file, honouring the skip check. All paths share one tally, because the
  caller asked for one scan and so gets one answer about whether it was complete. Prints
  `scan complete: N hashed, N skipped unchanged, N failed` and then every failed path.
  When anything was skipped because it is not a regular file, a second line follows:
  `skipped N not regular file(s), not read: fifo N, symlink N`, with one count per kind.
  **Exits 3 if anything failed;** a skipped entry does not count. A listed path that is
  neither a regular file nor a directory counts as a failure, and a symlink named on the
  command line is not followed.

- **check-file** *path*

  Hash one file and print any recorded paths holding the same checksum. Does not record
  anything. Exits 1 if *path* is not a regular file.

- **scan-dir-report** *path*

  Scan one directory and report the duplicates found within it in the same run. **Exits
  3 if the walk of the tree stopped early,** so that part of it was not scanned.

- **report-duplicates**

  Print every checksum in the database held by at least **--min-duplicates** files, with
  the paths under each. With **--prefix**, report duplicates only under that prefix —
  and note that **--min-duplicates** is then not applied, because the two are separate
  queries.

- **audit-db**

  Re-verify every recorded path: drop rows for files that no longer exist, rehash those
  whose (*size*, *mtime*) changed. **This action deletes rows; run it with --dry-run
  first.** Rows whose parent directory is also missing are reported as **SUSPECT** and
  **not** removed, because that is what an unmounted volume looks like —
  **--prune-missing-dirs** removes them deliberately. A row whose path is no longer a
  regular file — a symlink recorded by a version before #74, for example — is removed
  too, under the same **--dry-run**, and counted as **not regular**. Only a path that
  does not exist counts as missing. A path that cannot be examined, such as one under a
  directory the auditor cannot search, counts as a failure and its row is kept. Prints
  its settings and their origins before doing anything, then `audit complete: ...`.
  **Exits 3 if anything failed.** This is the only action that sets `PRAGMA
  journal_mode=WAL`, so a database that has never been audited is still in
  rollback-journal mode.

- **verify-db**

  Rehash recorded files and compare each against the **stored** checksum, reporting
  every mismatch with both values. **The only action that can detect silent
  corruption,** for the reason given under **The skip check** above. **Never writes to
  the database:** a verify that repaired the baseline on a mismatch would destroy the
  only evidence of corruption and would pass on its second run. Three outcomes, never
  two — matched, mismatched, could not read — and an unreadable file is **not** a pass.
  A recorded path that is not a regular file is not opened, and is reported as
  unreadable; **audit-db** removes such rows. Scope a long run with **--prefix**;
  verifying millions of recorded files takes hours. **Exits 4 on a mismatch, 3 on an
  unreadable file,** and 4 wins when both occur.

- **report-duplicate-sizes**

  Print the total size occupied by duplicate files.

- **report-prefix-count** **--prefix** *prefix*

  Print how many recorded paths begin with *prefix*. Requires **--prefix**.

- **report-files-for-prefix** **--prefix** *prefix*

  Print every recorded path beginning with *prefix*. Requires **--prefix**. Accepted by
  the parser but absent from the program's own **help** output; see **BUGS** below.

- **remove-record** *path*

  Remove the record for **exactly** *path*. With **--regex**, *path* is instead a
  regular expression matched against the **whole** recorded path (**re.fullmatch**).
  Removing a subtree is therefore explicit: `'/a/b/.*'`. Prints the number of rows
  removed.

- **compare-directories** **--dirA** *a* **--dirB** *b*

  Hash both trees in full, in process, and report the files unique to each. **Ignores
  the database entirely** — it is an O(n×m) comparison of two freshly hashed trees, not
  a query. Requires both **--dirA** and **--dirB**.

- **get-file-info** *path*

  Print the size, stored modification time and checksum the database holds for one path.

- **scan-unique-files** *path*

  Scan a directory and report the files whose checksum appears nowhere else. **Writes
  into the directory it scans:** a *.processed_files.txt* resume log at the root of the
  target tree, read back on the next run. Delete it to force a full recheck. Because the
  log lands inside the scanned tree, the next walk finds and checks it like any other
  file, so a second run over an unchanged tree reports exactly one file: the log. A file
  whose uniqueness could not be determined is logged as **unreadable** rather than
  reported either way, and is **rechecked** on the next run; a verdict is final, "could
  not check" is not.

- **help**

  Print the program's own usage text and exit 0. **-h**, **--help** and **-?** do the
  same. Note that **?** is a shell glob character and needs quoting as `'-?'`.

## OPTIONS

- **--version**

  Print the commit this code was built from, the build time and whether the source tree
  was clean, then exit 0. A bundle reports the values embedded when it was built; a
  source checkout says so and reads **git**(1) live. A question git cannot answer prints
  **CANNOT DETERMINE**, never a placeholder and never **clean**. The clean/dirty check
  is scoped to the *FileManager* directory only, so an edit elsewhere in the repository
  does not make a bundle's source dirty. Takes precedence over every action; **--help**
  in turn takes precedence over **--version**, since a caller asking both questions at
  once is asking how to use the tool.

- **--db-path** *path*

  The database file, or a directory to hold one. If *path* is an existing directory,
  *file_manager.db* is appended to it. **Default:** *./file_manager.db* in the current
  working directory.

- **--threads** *n*

  Width of the hashing pool. **Default: 4**. Threads are the only concurrency model; no
  database connection is ever shared between them.

- **--prefix** *prefix*

  Required by **report-prefix-count** and **report-files-for-prefix**. For **verify-db**
  it scopes the run to recorded paths under *prefix*, which is how a verify is made to
  fit in an available window. For **report-duplicates** it switches the query to prefix
  mode.

- **--exclude-prefix** *list*

  **audit-db** only: comma-separated prefixes whose paths are left untouched by the
  audit.

- **--min-duplicates** *n*

  **report-duplicates** only: report a checksum only when at least *n* files hold it.
  **Default: 2**. **It counts copies, not copies beyond the first** — 2 means a file and
  at least one other like it, so **--min-duplicates 3** returns groups of three.

- **--dirA** *path*\
  **--dirB** *path*

  The two trees **compare-directories** hashes. Both are required by that action and
  ignored by every other.

- **--regex**

  **remove-record** only: treat *path* as a regular expression matched against the whole
  recorded path. Without it the argument is taken literally. The regex form is opt-in
  because this action's argument looks like a path, and a path silently interpreted as a
  pattern deletes siblings.

- **--dry-run**

  **audit-db** only: report every change the audit would make, and make none of them.

- **--prune-missing-dirs**

  **audit-db** only: also remove rows whose parent directory is gone. Off by default;
  see **audit-db** above for why.

## EXIT STATUS

An invalid invocation exits non-zero, so a caller under `set -e` stops.

- **0**

  The action completed and read everything it was asked to read, or help or
  **--version** was requested.

- **1**

  A required argument was missing or invalid. Nothing was recorded.

- **2**

  The argument parser rejected the command line — an unknown option, or an action
  outside the accepted set. Nothing was recorded.

- **3**

  **scan**, **scan-dir-report**, **audit-db** or **verify-db** completed but could not
  read part of what it was asked to read. That includes a walk that stopped early: the
  files already found are recorded, the rest of the tree is not, and **scan** lists the
  directory as failed with \`**walk stopped early:** *reason*'**(#75).** **Part of the
  tree was recorded or checked and part was not.** The counts and every failed path are
  on standard output.

  3 is deliberately neither 1 nor 2: those mean nothing happened at all, while this
  leaves a partial index behind — and a partial index **cannot be detected afterwards,**
  because the database looks the same whether a file was absent from the tree or merely
  unreadable. **This is the status an unattended run must check.**

- **4**

  **verify-db** found a recorded file whose contents no longer match its stored
  checksum. Not 3: 3 means part of the answer is unknown, 4 means the answer is known
  and bad, and an operator does something different about each. A mismatch outranks an
  unreadable file when both occur in one run.

## OUTPUT

**The split between the two streams is a contract, not a convention.** A scheduled scan
is normally run with `2>/dev/null` to suppress the per-file log, so anything that is the
**result** of the run goes to standard output and survives that redirection.

- **Standard output**

  The run header; the per-action report; the scan, audit and verify summaries with their
  failed and mismatched paths; and, during a scan, a bare **.** per skipped file. Each
  summary is preceded by a blank line, because those dots otherwise leave it at the end
  of a very long one. Failure lists are truncated at 20 entries, with a count of the
  remainder; every one of them is still on its own log line.

- **Standard error**

  All logging, at **INFO**, in the form `%(asctime)s - %(levelname)s - %(message)s`.

Every action that runs prints a header first, before it creates or opens anything:

```
FileManager run
started : 2026-11-17 17:53:54 MST
version : 1c720f402037ce3f4f6941b2bb7d893fcf10bb93 (source checkout, clean)
action  : scan
paths   : /home2
db      : /var/lib/filemanager/home2.db
threads : 2
```

The zone is part of the requirement, not decoration: this output is read out of a log
days later, and a bare clock time gets read against the wrong zone. **help** and
**--version** print no header — they are questions about the tool rather than runs of
it.

**audit-db** and **verify-db** additionally print each setting with its **origin**
before doing any work:

```
verify-db settings:
  db_path = /var/lib/filemanager/home2.db  (set)
  threads = 4  (default)
  prefix  = (every recorded path)  (default)
```

`(set)` versus `(default)` is the point. A value that merely looks right is not evidence
that it was set, and **audit-db** deletes rows — the configuration that governed a past
run is not recoverable from its effects. A setting whose name looks like a credential is
refused outright rather than printed, because this output is written to disk.

## FILES

- *./file_manager.db*

  The database, when **--db-path** is not given.

- *\<scanned tree\>*/.processed_files.txt

  **scan-unique-files** resume log, written inside the directory being scanned.

- *dist/FileManager.pyz*

  The bundle, built by *scripts/build-pyz.sh*.

**Two notes on the database file.** Its parent directory is **not** created for you:
name a directory that does not exist and the run fails with an uncaught SQLite error
rather than a message (see **BUGS**). And every action except **help** and **--version**
opens and initialises the database before dispatching, so even **compare-directories**,
which never queries it, creates an empty one as a side effect.

## ENVIRONMENT

**The program itself reads no environment variables.** The following are read by the
tooling around it and are listed because they are easily mistaken for program options.

- **FM_ALLOW_DIRTY**

  Read by *scripts/build-pyz.sh*. The build refuses to run while anything under
  *FileManager/* is uncommitted, because the artifact would then be unidentifiable.
  Setting it to exactly **1** builds anyway, and the artifact reports **dirty at build
  time** permanently.

- **FM_DB**, **FM_THREADS**, **FM_VIDEO_DIRS**

  Read by the *fm-\*.sh* wrapper scripts to override the database, the thread count and
  the scanned directories.

- **VIRTUAL_ENV**

  Not read deliberately, but worth knowing about: a shell that inherited it from another
  project silently beats the **pyenv**(1) shim, so a bare **python** can be a different
  interpreter from the one `pyenv version` reports. The wrappers use `pyenv exec` for
  exactly this reason.

## EXAMPLES

Index two trees with eight threads, keeping the database off both of them:

```
filemanager --threads 8 --db-path /var/lib/filemanager/home2.db \
    scan /home2,/mnt/internal/BACKUP/00
```

Run the same scan from **cron**(8), checking the status that matters:

```
filemanager --threads 8 --db-path /var/lib/filemanager/home2.db \
    scan /home2 2>/dev/null
case $? in
    0) ;;                                  # complete
    3) echo "PARTIAL INDEX - see the failed paths above" >&2 ;;
    *) echo "scan did not run" >&2 ;;
esac
```

Report what the audit would delete, before letting it delete anything:

```
filemanager --db-path /var/lib/filemanager/home2.db audit-db --dry-run
filemanager --db-path /var/lib/filemanager/home2.db audit-db \
    --exclude-prefix /mnt/offline,/mnt/other
```

Read the stored checksums back for one volume, which is the only way to find corruption
that has already happened:

```
filemanager --threads 8 --db-path /var/lib/filemanager/home2.db \
    verify-db --prefix /mnt/internal/BACKUP/00
```

Report groups of three or more identical files, then remove a subtree's records:

```
filemanager --db-path /var/lib/filemanager/home2.db \
    report-duplicates --min-duplicates 3
filemanager --db-path /var/lib/filemanager/home2.db \
    remove-record '/mnt/retired/.*' --regex
```

Ask an installed bundle which commit it is:

```
filemanager --version
FileManager
commit : 1c720f402037ce3f4f6941b2bb7d893fcf10bb93
built  : 2026-11-17 13:50:31 MST
tree   : clean
source : zipapp bundle
```

## DATABASE

One table, created by every run that reaches an action:

```
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY,
    md5sum        TEXT,
    size          INTEGER,
    last_modified INTEGER,
    path          TEXT UNIQUE
)
```

There are no indexes beyond the implicit unique index on *path*, so duplicate reporting
is a full table scan and group-by.

**Any change to how last_modified is stored or compared invalidates every** **existing
database** and forces a full rehash of every recorded file, because the skip check
compares the stored value directly.

Connections are never shared or reused: one is opened per unit of work, used, and
closed. A locked database is retried up to 10 times at 0.1s intervals, catching **only**
an **OperationalError** containing "database is locked" and re-raising anything else, so
a malformed statement fails immediately rather than a second later.

## NOTES

### Choosing between scan and verify-db

They answer different questions and neither substitutes for the other. **scan** answers
"is the index current?" cheaply, by trusting (*size*, *mtime*). **verify-db** answers
"is what the index says still true?" expensively, by rehashing.

Whether that second question needs asking depends on the filesystem. On one with data
checksums — **btrfs**(5), ZFS — the kernel already detects corruption per block, and
**btrfs-scrub**(8) is the cheaper tool for it. On **ext4**(5), which checksums metadata
only, an application-level verify is the only thing that will notice a file whose
contents changed without its mtime.

### Memory

**scan** holds at most 68,759 queued file paths in memory, about 8 MiB for paths of 67
characters; the walk waits when the hashing workers fall behind (#67). Longer paths cost
about one byte more per character. **verify-db** is not bounded: it materialises every
row it will check before it starts, on the order of 1.3 GiB for 5.6 million rows; see
**BUGS**.

### Database placement

Keep the database off the trees being scanned, and on an SSD if there is one. A scan
opens a connection per file and commits one transaction per recorded file, so the
database is the write-heavy part of the run; putting it inside a scanned tree
additionally makes it an input to the next walk.

## BUGS

Known and open, with the issue numbers in [the SystemUtils
board](https://github.com/users/JeffreyPeacock/projects/14):

- **verify-db materialises every row (#68)**

  The recorded paths are read into a list before any hashing starts, rather than
  streamed. Use **--prefix** to bound it.

- **A missing database directory is reported as an invalid argument (#69)**

  Naming a **--db-path** whose parent directory does not exist produces an uncaught
  **sqlite3.OperationalError** and a traceback, exiting 1 — a status this page defines
  as a bad argument. Create the directory first.

- **report-files-for-prefix is undocumented and validated late**

  The action is accepted by the parser but does not appear in the program's own **help**
  output, and its **--prefix** check runs after the header has been printed and the
  database created, rather than alongside the other argument checks.

## SEE ALSO

**md5sum**(1), **sqlite3**(1), **find**(1), **btrfs-scrub**(8), **cron**(8)

In the repository: *FileManager/README.md* for orientation, *FileManager/CLAUDE.md* for
the operational reference, *FileManager/docs/Architecture+Design.md* for why each of the
above is the way it is, and *docs/Development-Principles.md* for the rules those
decisions follow.

## AUTHOR

Jeffrey Peacock. Part of [SystemUtils](https://github.com/JeffreyPeacock/SystemUtils).
