#!/usr/bin/env bash
#
# Export a Claude Code session transcript to readable text, with secrets masked.
#
# Claude Code keeps each session as JSONL under ~/.claude/projects/<encoded-cwd>/.
# That is machine-readable, enormous, and full of nested tool payloads. This
# renders it as plain text and masks what a session log picks up by accident.
#
# Ported from SAMD21-LoRa-ProRF. Two things differ, both because this is a
# different kind of project:
#
#   1. THE MASKING RULES. That project's sensitive material was location --
#      GPS coordinates off a receiver. Here the transcript is mostly file
#      paths and MD5 checksums, which are the CONTENT and must survive. What
#      gets masked is the username inside a home path, plus the incidental
#      email/credential shapes any session picks up. See scripts/lib/mask.py.
#
#   2. SESSION LOOKUP. That repo is one project at one path. This is a
#      container repo, so a session may have been started in the repo root OR
#      in a utility subdirectory, each of which Claude Code encodes to a
#      different log directory. This script searches every candidate rather
#      than assuming one, and says which it used.
#
# Masking is ON by default and has to be switched off deliberately. That is the
# right way round: a transcript is easy to paste somewhere public.

set -euo pipefail

# shellcheck source-path=SCRIPTDIR
# shellcheck source=lib/common.sh
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

CLAUDE_HOME="${CLAUDE_HOME:-${HOME}/.claude}"
OUT_DIR="${PROJECT_DIR}/.claude_artifacts/transcripts"
SESSION=''
OUT_PATH=''
SCOPE=''
MASK=1
KEEP_THINKING=1
MAX_TOOL_IN=2000
MAX_TOOL_OUT=3000
declare -a EXTRA_SECRETS=()
# Literals to mask, one per line. Preferred over --secret: a value typed on the
# command line lands in shell history AND in the next transcript.
SECRETS_FILE="${PROJECT_DIR}/.claude_artifacts/mask-secrets.txt"

usage() {
    cat <<USAGE
Usage: $(basename -- "$0") [options]

Render a Claude Code session log as readable text, with secrets masked.
Defaults to the most recently modified session across the whole repository.

  --session ID|PATH   session UUID, or a path to a .jsonl (default: newest)
  --scope DIR         only sessions started in DIR (e.g. FileManager)
  --out PATH          output file (default: <out-dir>/YYYY.MM.DD-transcript.txt)
  --out-dir DIR       default ${OUT_DIR#"${PROJECT_DIR}"/}
  --secret STRING     also mask this literal; repeatable (prefer --secrets-file)
  --secrets-file PATH literals to mask, one per line, # for comments
                      (default: .claude_artifacts/mask-secrets.txt if present)
  --no-mask           do NOT mask anything (think before using this)
  --no-thinking       omit assistant reasoning blocks
  --max-tool-in N     truncate tool inputs at N chars (default ${MAX_TOOL_IN})
  --max-tool-out N    truncate tool results at N chars (default ${MAX_TOOL_OUT})
  --list              list this repository's sessions and exit
  -h, --help          this message

Always masked: the username in a home path, email addresses, decimal-degree
coordinate pairs, street addresses, credential-shaped assignments and PEM
private-key headers. MD5 checksums, file sizes and directory names are left
alone deliberately -- they are the content of a FileManager log.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --session)      SESSION="${2:?}"; shift 2 ;;
        --scope)        SCOPE="${2:?}"; shift 2 ;;
        --out)          OUT_PATH="${2:?}"; shift 2 ;;
        --out-dir)      OUT_DIR="${2:?}"; shift 2 ;;
        --secret)       EXTRA_SECRETS+=("${2:?}"); shift 2 ;;
        --secrets-file) SECRETS_FILE="${2:?}"; shift 2 ;;
        --no-mask)      MASK=0; shift ;;
        --no-thinking)  KEEP_THINKING=0; shift ;;
        --max-tool-in)  MAX_TOOL_IN="${2:?}"; shift 2 ;;
        --max-tool-out) MAX_TOOL_OUT="${2:?}"; shift 2 ;;
        --list)         SESSION='__list__'; shift ;;
        -h|--help)      usage; exit 0 ;;
        *) printf 'unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

need python3

# Claude Code encodes the project path by replacing both / and . with -
encode_dir() { printf '%s\n' "$1" | sed 's|[/.]|-|g'; }

# A session may have been started in the repo root or in any utility
# subdirectory. Collect every log directory that actually exists.
declare -a LOG_DIRS=()
add_log_dir() {
    local d="${CLAUDE_HOME}/projects/$(encode_dir "$1")"
    [[ -d ${d} ]] || return 0
    local existing
    for existing in ${LOG_DIRS[@]+"${LOG_DIRS[@]}"}; do
        [[ ${existing} == "${d}" ]] && return 0
    done
    LOG_DIRS+=("${d}")
}

if [[ -n ${SCOPE} ]]; then
    scope_abs="$(cd -- "${SCOPE}" 2>/dev/null && pwd)" \
        || die "--scope: no such directory: ${SCOPE}"
    add_log_dir "${scope_abs}"
    [[ ${#LOG_DIRS[@]} -gt 0 ]] || die "no session logs for ${scope_abs}"
else
    add_log_dir "${PROJECT_DIR}"
    for sub in "${PROJECT_DIR}"/*/; do
        [[ -d ${sub} ]] && add_log_dir "${sub%/}"
    done
fi

[[ ${#LOG_DIRS[@]} -gt 0 ]] \
    || die "no session logs for this repository under ${CLAUDE_HOME}/projects/"

all_logs() {
    local d
    for d in "${LOG_DIRS[@]}"; do
        find "${d}" -maxdepth 1 -name '*.jsonl' -printf '%T@ %p\n' 2>/dev/null
    done
}

if [[ ${SESSION} == '__list__' ]]; then
    section "sessions for ${PROJECT_DIR##*/}"
    while read -r _ f; do
        [[ -n ${f} ]] || continue
        printf '  %s  %6s  %-36s  %s\n' \
            "$(date -r "${f}" +'%Y-%m-%d %H:%M')" \
            "$(du -h "${f}" | cut -f1)" \
            "$(basename -- "${f}" .jsonl)" \
            "$(basename -- "$(dirname -- "${f}")")"
    done < <(all_logs | sort -rn)
    exit 0
fi

# Resolve which log to render
if [[ -z ${SESSION} ]]; then
    SRC="$(all_logs | sort -rn | head -n 1 | cut -d' ' -f2-)"
    [[ -n ${SRC} ]] || die "no .jsonl session logs found (try --list)"
elif [[ -f ${SESSION} ]]; then
    SRC="${SESSION}"
else
    SRC=''
    for d in "${LOG_DIRS[@]}"; do
        [[ -f "${d}/${SESSION}.jsonl" ]] && { SRC="${d}/${SESSION}.jsonl"; break; }
    done
    [[ -n ${SRC} ]] || die "no such session: ${SESSION} (try --list)"
fi

[[ -n ${OUT_PATH} ]] || OUT_PATH="${OUT_DIR}/$(date +'%Y.%m.%d')-transcript.txt"
mkdir -p -- "$(dirname -- "${OUT_PATH}")"

# Refuse to write somewhere git would track. A transcript is exactly the kind of
# file that carries a credential into a public repository -- and this one IS
# public.
#
# The check only applies INSIDE the work tree: git reports any path outside it as
# "not ignored", which is true but irrelevant -- git cannot track /tmp either.
ABS_OUT="$(realpath -m -- "${OUT_PATH}")"
if [[ ${ABS_OUT} == "${PROJECT_DIR}"/* ]] \
   && git -C "${PROJECT_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if ! git -C "${PROJECT_DIR}" check-ignore -q "${ABS_OUT}" 2>/dev/null; then
        warn "${OUT_PATH} is inside the repository and NOT gitignored."
        warn "Transcripts routinely contain credentials. Add it to .gitignore first,"
        warn "or pass --out to a path that is ignored."
        die "refusing to write a transcript to a tracked location"
    fi
fi

section 'export'
info "source : ${SRC}"
info "output : ${OUT_PATH}"
info "masking: $([[ ${MASK} -eq 1 ]] && echo on || echo 'OFF -- secrets will be written in clear')"

# EXTRA_SECRETS is an array, and bash cannot export arrays -- exporting it
# passes nothing at all, silently. Flatten it into a separate scalar first.
OUT="${OUT_PATH}"
if [[ -f ${SECRETS_FILE} ]]; then
    while IFS= read -r line; do
        [[ -z ${line} || ${line} == '#'* ]] && continue
        EXTRA_SECRETS+=("${line}")
    done < "${SECRETS_FILE}"
    info "secrets file: ${SECRETS_FILE} ($(grep -cvE '^\s*(#|$)' "${SECRETS_FILE}") entries)"
fi

SECRETS_BLOB="$(printf '%s\n' ${EXTRA_SECRETS[@]+"${EXTRA_SECRETS[@]}"})"
LIB_DIR="${SCRIPTS_DIR}/lib"
export SRC OUT MASK KEEP_THINKING MAX_TOOL_IN MAX_TOOL_OUT SECRETS_BLOB LIB_DIR

if ! python3 - <<'PYTHON'
import json, os, sys, datetime

SRC   = os.environ['SRC']
DST   = os.environ['OUT']
MASK  = os.environ['MASK'] == '1'
THINK = os.environ['KEEP_THINKING'] == '1'
MAXIN = int(os.environ['MAX_TOOL_IN'])
MAXOUT= int(os.environ['MAX_TOOL_OUT'])
EXTRA = [s for s in os.environ.get('SECRETS_BLOB','').split('\n') if s]

RULE = '=' * 78

def stamp(o):
    t = o.get('timestamp')
    if not t: return ''
    try:
        return datetime.datetime.fromisoformat(t.replace('Z','+00:00')) \
                 .astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(t)

def clip(v, n):
    s = v if isinstance(v, str) else json.dumps(v, indent=1, default=str)
    return s if len(s) <= n else s[:n] + f"\n… [truncated, {len(s)-n} more chars]"

counts = {'user':0,'assistant':0,'thinking':0,'tool_use':0,'tool_result':0,'bad':0}
out = []

for line in open(SRC, encoding='utf-8'):
    line = line.strip()
    if not line: continue
    try:
        o = json.loads(line)
    except Exception:
        counts['bad'] += 1
        continue
    if o.get('type') not in ('user','assistant'): continue
    msg = o.get('message')
    if not isinstance(msg, dict): continue
    role = msg.get('role','?')
    counts[role] = counts.get(role,0)+1
    out.append(f"\n{RULE}\n{role.upper()}   {stamp(o)}\n{RULE}")

    content = msg.get('content')
    if isinstance(content, str):
        out.append(content); continue
    for b in (content or []):
        if not isinstance(b, dict):
            out.append(str(b)); continue
        t = b.get('type')
        if t == 'text':
            out.append(b.get('text',''))
        elif t == 'thinking':
            counts['thinking'] += 1
            if THINK:
                out.append(f"\n--- [thinking] ---\n{b.get('thinking','').strip()}\n--- [/thinking] ---")
        elif t == 'tool_use':
            counts['tool_use'] += 1
            out.append(f"\n>>> TOOL CALL: {b.get('name')}\n{clip(b.get('input',{}), MAXIN)}")
        elif t == 'tool_result':
            counts['tool_result'] += 1
            c = b.get('content')
            if isinstance(c, list):
                c = "\n".join(x.get('text','') if isinstance(x,dict) else str(x) for x in c)
            out.append(f"\n<<< TOOL RESULT{' (ERROR)' if b.get('is_error') else ''}:\n{clip(c or '', MAXOUT)}")
        else:
            out.append(f"\n[{t}]\n{clip(b, 600)}")

body = (f"{RULE}\nClaude Code session transcript\n"
        f"source  : {SRC}\n"
        f"exported: {datetime.datetime.now():%Y-%m-%d %H:%M}\n"
        f"masking : {'on' if MASK else 'OFF'}\n{RULE}\n") + "\n".join(out) + "\n"

# The patterns live in lib/mask.py so that masking and the verification below
# cannot drift apart. Two copies is how a secret leaks twice.
sys.path.insert(0, os.environ['LIB_DIR'])
from mask import mask as _mask, residual as _residual

masked = {}
if MASK:
    body, masked = _mask(body, EXTRA)

# Verify with the same patterns. Anything still matching is a genuine leak,
# not a prose false positive, because the patterns require a value to follow.
residual = _residual(body)

open(DST,'w',encoding='utf-8').write(body)

print(f"  rendered {counts['user']} user / {counts['assistant']} assistant turns, "
      f"{counts['tool_use']} tool calls, {counts['thinking']} thinking blocks")
if counts['bad']:
    print(f"  WARNING: {counts['bad']} unparseable lines skipped")
if MASK:
    print("  masked  : " + (", ".join(f"{k} x{v}" for k,v in masked.items()) if masked else "nothing matched"))
print(f"  size    : {len(body):,} chars, {body.count(chr(10)):,} lines")
if MASK:
    if residual:
        print("  RESIDUAL: " + ", ".join(f"{k} x{v}" for k,v in residual.items()))
        sys.exit(3)
    print("  residual: none — no pattern still matches a value")
PYTHON
then
    die 'masking left secret material in the output — not safe to share'
fi

ok 'export complete'
info 'the scan only knows the patterns above — skim the file before sharing it'

report_result
