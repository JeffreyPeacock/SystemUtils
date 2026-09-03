"""Secret-masking patterns shared by anything in this repo that renders a log.

There is exactly one definition of what a secret looks like, and it is used
BOTH to mask and to verify the masking afterwards. If those two ever diverge
the verification becomes theatre, so they share this list.

A pattern is (label, regex). The regex must capture the kept prefix in group 1
and the secret in group 2, because masking replaces the match with
group(1) + '***'. A (?!\\*) guard stops an already-masked value from matching
again, which is what lets the residual check mean something.

Ported from SAMD21-LoRa-ProRF. The machinery is unchanged; the RULES ARE NOT,
because what is sensitive here is different -- see below.
"""

import hashlib
import re

# WHAT IS ACTUALLY SENSITIVE IN THIS REPO.
#
# FileManager's entire output is filesystem paths and MD5 checksums, so the
# usual instinct -- mask the paths -- would delete the transcript's content.
# The checksums, sizes and directory names are the point and are left alone.
#
# What identifies a person here is narrower: the USERNAME inside a home path,
# which appears on nearly every line of a scan log, and the incidental things
# any session picks up from a shell prompt or a pasted message.
PATTERNS = [
    # The username segment of a home directory, and nothing else about the
    # path. /home/alice/Workspace/x -> /home/***/Workspace/x, so the tree
    # structure survives and the person does not.
    ('home-user',
     r'((?:/home|/Users)/)(?!\*\*\*)([A-Za-z0-9._-]+)'),

    # Email address.
    ('email',
     r'()([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})'),

    # A bare decimal-degree pair -- a photo archive's directory names or an
    # EXIF dump can carry one.
    ('coordinates',
     r'()(-?\d{1,2}\.\d{5,}\s*,\s*-?1?\d{1,2}\.\d{5,})'),

    # A street address, in the form an order confirmation or invoice uses.
    ('street-address',
     r'(?i)()(\d{2,5}(?:\s+[A-Z][A-Za-z]*){1,4}\s+(?:CIR|ST|AVE|RD|DR|LN|BLVD|CT|WAY)\b[^\n]*)'),

    # Generic credential shapes, in case anything ever grows one.
    ('token',
     r'(?i)(\b(?:api[_-]?key|token|secret|password|passwd)\s*[=:]\s*)(?!\*)(\S{8,})'),
    ('private-key',
     r'()(-----BEGIN [A-Z ]*PRIVATE KEY-----)'),
]

# Deliberately NOT masked: MD5 checksums, file sizes, mtimes, and the
# non-home part of any path. A transcript masked until it is unreadable
# defeats the exercise, and those four are the whole content of a scan log.


def mask(body, extra=()):
    """Mask every pattern, then every literal in `extra`.

    Returns (masked_body, {label: count}).
    """
    counts = {}
    for label, pat in PATTERNS:
        body, n = re.subn(pat, lambda m: m.group(1) + '***', body, flags=re.M)
        if n:
            counts[label] = n
    for literal in extra:
        n = body.count(literal)
        if n:
            body = body.replace(literal, '***')
            counts[_label(literal)] = n
    return body, counts


def _label(literal):
    """A stable name for a literal that does not disclose any of it.

    Never print a prefix of the literal here: that writes part of a secret
    into the very report claiming to have masked it.
    """
    digest = hashlib.sha256(literal.encode()).hexdigest()[:8]
    return f'literal sha:{digest} ({len(literal)} chars)'


def residual(body):
    """Anything still matching after mask() is a real leak, not a false
    positive, because every pattern requires a value to follow the key."""
    out = {}
    for label, pat in PATTERNS:
        hits = re.findall(pat, body, flags=re.M)
        if hits:
            out[label] = len(hits)
    return out


def load_literals(path):
    """Read a secrets file: one literal per line, '#' comments, blanks ignored.

    Literals catch what no pattern can. Missing file is not an error.
    """
    try:
        with open(path, encoding='utf-8') as fh:
            return [ln.strip() for ln in fh
                    if ln.strip() and not ln.lstrip().startswith('#')]
    except FileNotFoundError:
        return []
