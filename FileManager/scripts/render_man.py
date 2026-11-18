#!/usr/bin/env python3
"""Render a troff man page as readable markdown.

`man/filemanager.1` is the source of truth for the manual: it is the format
`man` can display and the one that gets installed. But troff is not a format
anyone wants to read in an editor tab, so this writes `man/filemanager.md`
beside it, and `tests/test_man_page.py` fails while the two disagree.

Why a renderer here rather than `pandoc` or `groff | col -b`:

* **It has to run where the gate runs.** The check that the markdown is current
  compares it against a fresh render, so the renderer has to be available in
  CI. pandoc's output also differs between pandoc versions, which would make a
  byte comparison fail on a version bump rather than on a real drift.
* **pandoc's output was measured and was wrong in three places.** Both
  `.SY`/`.YS` synopsis groups collapsed into one run-on paragraph; `.BI scan
  " path"` came out as `**scan*** path*`, which is not valid emphasis; and the
  troff `` ` ``...`'` quoting became literal backslash-escaped punctuation
  instead of a code span.
* Standard library only, like the rest of this project.

**It refuses rather than guesses.** A macro or an escape this file does not
know raises `UnsupportedTroff` and nothing is written. The alternative --
dropping what it does not recognise -- produces a markdown file that looks
complete and is quietly missing a paragraph, which is the same class of failure
as a check that cannot run reporting success. The supported set is exactly what
`man/filemanager.1` uses today; widening the page means widening this file, and
the error message says which line stopped it.

Usage:
    scripts/render_man.py [input.1 [output.md]]

Exit codes:
    0   written
    1   the input could not be read
    2   the input uses troff this renderer does not support (nothing written)
"""

from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path

#: Prose is wrapped so the file is readable in an editor and diffs line by
#: line. Code blocks and tables are never wrapped.
PROSE_WIDTH = 88

#: Synopsis lines are wrapped narrower, because they sit in a code block that
#: does not reflow and is read on a terminal as often as in a browser.
SYNOPSIS_WIDTH = 78

#: Escapes with a literal expansion. Font escapes (`\fB` and friends) are
#: handled separately because they change state rather than emit text.
CHAR_ESCAPES = {
    r'\-': '-',
    r'\(em': '—',   # em dash
    r'\(aq': "'",        # apostrophe, the unambiguous form
    r'\(mu': '×',   # multiplication sign
    r'\e': '\\',
    r'\ ': ' ',          # non-breaking space; already a plain space by here
}

FONT_ESCAPES = {r'\fB': 'B', r'\fI': 'I', r'\fR': 'R', r'\fP': 'P'}

#: Every escape this renderer knows, longest first so `\(em` is matched before
#: a bare `\(`.
_ESCAPE_RE = re.compile(
    '|'.join(re.escape(e) for e in
             sorted(list(CHAR_ESCAPES) + list(FONT_ESCAPES), key=len, reverse=True))
    + r'|\\.'
)

#: A placeholder for `\ ` (an escaped, non-breaking space) while the line is
#: split into arguments. Without it, `int(x)\ *\ 1000` would split into three
#: arguments and be reassembled wrong.
_NBSP = '\x00'


class UnsupportedTroff(Exception):
    """The page uses troff this renderer does not implement.

    Carries the line number and the text, because the whole point of raising
    instead of skipping is that someone can go and look at the line.
    """


class Run:
    """A span of text in one font: 'R' roman, 'B' bold, 'I' italic."""

    __slots__ = ('text', 'font')

    def __init__(self, text: str, font: str) -> None:
        self.text = text
        self.font = font

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f'Run({self.text!r}, {self.font!r})'


# --------------------------------------------------------------------------
# Lexing
# --------------------------------------------------------------------------

def split_args(rest: str, lineno: int) -> list[str]:
    """Split a macro's arguments the way troff does.

    Double quotes group words; everything else splits on whitespace. An
    unterminated quote is an error rather than a silent "rest of the line",
    because the two produce different output and only one of them was meant.
    """
    protected = rest.replace(r'\ ', _NBSP)
    args: list[str] = []
    i, n = 0, len(protected)
    while i < n:
        if protected[i].isspace():
            i += 1
            continue
        if protected[i] == '"':
            end = protected.find('"', i + 1)
            if end == -1:
                raise UnsupportedTroff(
                    f'line {lineno}: unterminated double quote in {rest!r}'
                )
            args.append(protected[i + 1:end])
            i = end + 1
        else:
            start = i
            while i < n and not protected[i].isspace():
                i += 1
            args.append(protected[start:i])
    return [a.replace(_NBSP, ' ') for a in args]


def expand(arg: str, base_font: str, lineno: int) -> list[Run]:
    """Turn one argument into runs, honouring in-argument font escapes."""
    runs: list[Run] = []
    font, previous = base_font, base_font
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            runs.append(Run(''.join(buffer), font))
            buffer.clear()

    position = 0
    for match in _ESCAPE_RE.finditer(arg):
        buffer.append(arg[position:match.start()])
        token = match.group(0)
        position = match.end()
        if token in CHAR_ESCAPES:
            buffer.append(CHAR_ESCAPES[token])
        elif token in FONT_ESCAPES:
            flush()
            wanted = FONT_ESCAPES[token]
            font, previous = (previous, font) if wanted == 'P' else (wanted, font)
        else:
            raise UnsupportedTroff(
                f'line {lineno}: unsupported escape {token!r} in {arg!r}'
            )
    buffer.append(arg[position:])
    flush()
    return runs


#: Macros whose arguments alternate between fonts and are joined with NO
#: separator -- `.BR fdupes (1)` is "fdupes" bold against "(1)" roman.
ALTERNATING = {
    'BR': 'BR', 'RB': 'RB', 'BI': 'BI', 'IB': 'IB', 'IR': 'IR', 'RI': 'RI',
}

#: Macros that set one font for every argument, joined with spaces.
SINGLE_FONT = {'B': 'B', 'I': 'I', 'R': 'R'}


def macro_runs(macro: str, args: list[str], lineno: int) -> list[Run]:
    """Render a font macro's arguments as runs."""
    runs: list[Run] = []
    if macro in SINGLE_FONT:
        font = SINGLE_FONT[macro]
        for index, arg in enumerate(args):
            if index:
                runs.append(Run(' ', font))
            runs.extend(expand(arg, font, lineno))
        return runs

    pattern = ALTERNATING[macro]
    for index, arg in enumerate(args):
        runs.extend(expand(arg, pattern[index % len(pattern)], lineno))
    return runs


# --------------------------------------------------------------------------
# Rendering runs to markdown
# --------------------------------------------------------------------------

_MD_SPECIAL = str.maketrans({
    '\\': r'\\', '`': r'\`', '*': r'\*', '[': r'\[', ']': r'\]',
    '<': r'\<', '>': r'\>', '|': r'\|',
})

#: An underscore only opens emphasis at a word boundary, so `last_modified`
#: needs no escaping and escaping it would put backslashes in front of half the
#: identifiers in the page.
_LONE_UNDERSCORE = re.compile(r'(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])')


def md_escape(text: str) -> str:
    """Escape what markdown would otherwise interpret."""
    return _LONE_UNDERSCORE.sub(r'\\_', text.translate(_MD_SPECIAL))


def plain(runs: list[Run]) -> str:
    """The text with every font dropped -- for code blocks and comparisons."""
    return ''.join(run.text for run in runs)


def _emphasise(text: str, marker: str) -> str:
    """Wrap `text` in `marker`, keeping surrounding spaces outside it.

    `.BI scan " path"` gives an italic argument that begins with a space, and
    `* path*` is not emphasis in markdown -- the marker has to hug the word.
    """
    stripped = text.strip()
    if not stripped:
        return text
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return f'{lead}{marker}{md_escape(stripped)}{marker}{trail}'


def to_markdown(runs: list[Run]) -> str:
    """Render runs as inline markdown.

    The one special case is troff's `` ` ``...`'` quoting, which this page uses
    for literal commands and output. Rendered literally it becomes backslashed
    punctuation; rendered as a code span it becomes what it meant.
    """
    if len(runs) >= 3 and runs[0].text == '`' and runs[-1].text.startswith("'"):
        content = plain(runs[1:-1])
        if '`' not in content:
            return f'`{content}`{md_escape(runs[-1].text[1:])}'

    merged: list[Run] = []
    for run in runs:
        if merged and merged[-1].font == run.font:
            merged[-1].text += run.text
        else:
            merged.append(Run(run.text, run.font))

    out: list[str] = []
    for run in merged:
        if run.font == 'B':
            out.append(_emphasise(run.text, '**'))
        elif run.font == 'I':
            out.append(_emphasise(run.text, '*'))
        else:
            out.append(md_escape(run.text))
    return ''.join(out)


def wrap(text: str, width: int, indent: str = '') -> list[str]:
    """Wrap a paragraph. Hyphens are never break points -- `--db-path` is one
    token and splitting it across lines would invent an option."""
    return textwrap.wrap(
        text, width=width, initial_indent=indent, subsequent_indent=indent,
        break_long_words=False, break_on_hyphens=False,
    ) or [indent.rstrip()]


# --------------------------------------------------------------------------
# The document
# --------------------------------------------------------------------------

# `.UR` is deliberately absent: a link is inline, and ending the paragraph
# at it put the link on a line of its own with the sentence it belongs to
# left dangling above it.
BLOCK_ENDERS = {'TP', 'TQ', 'PP', 'SH', 'SS', 'EX', 'SY', 'IP'}

#: Macros that carry no arguments and only end or begin a block.
NO_ARG = {'PP', 'YS', 'EE', 'TP', 'TQ'}


class Renderer:
    """Turn the lines of a man page into markdown.

    One pass, with the current block held in `self.pending`: troff joins
    consecutive text lines into a paragraph, so a line cannot be rendered until
    the next macro says the paragraph has ended.
    """

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.out: list[str] = []
        self.pending: list[str] = []        # the paragraph being accumulated
        self.title: dict[str, str] = {}
        self.item_depth = 0                 # inside a .TP list?
        self.sections: list[str] = []       # for the report at the end

    # -- output helpers ----------------------------------------------------

    def blank(self) -> None:
        if self.out and self.out[-1] != '':
            self.out.append('')

    def flush_paragraph(self) -> None:
        """Emit the accumulated paragraph, indented if inside a list item."""
        if not self.pending:
            return
        text = ' '.join(self.pending)
        self.pending = []
        indent = '  ' if self.item_depth else ''
        self.blank()
        self.out.extend(wrap(text, PROSE_WIDTH, indent))

    # -- the pass ----------------------------------------------------------

    def run(self) -> str:
        index = 0
        total = len(self.lines)
        while index < total:
            raw = self.lines[index].rstrip('\n')
            lineno = index + 1

            if raw.startswith('.\\"') or raw.strip() == '.':
                index += 1
                continue

            if not raw.startswith('.'):
                self.pending.append(to_markdown(expand(raw, 'R', lineno)))
                index += 1
                continue

            macro, _, rest = raw[1:].partition(' ')
            args = split_args(rest, lineno) if rest.strip() else []

            if macro in BLOCK_ENDERS or macro in NO_ARG:
                self.flush_paragraph()

            handler = getattr(self, f'_do_{macro}', None)
            if handler is None:
                raise UnsupportedTroff(f'line {lineno}: unsupported macro .{macro}')
            index = handler(args, index, lineno)

        self.flush_paragraph()
        return self.header() + '\n'.join(self.out).rstrip() + '\n'

    # -- document furniture ------------------------------------------------

    def header(self) -> str:
        name = self.title.get('name', 'MANUAL')
        section = self.title.get('section', '1')
        manual = self.title.get('manual', '')
        source = self.title.get('source', '')
        date = self.title.get('date', '')
        footer = ' · '.join(p for p in (manual, source, date) if p)
        return (
            f'# {name}({section})\n'
            '\n'
            '> **Generated file — do not edit.** Rendered from\n'
            '> [`man/filemanager.1`](filemanager.1) by `scripts/render_man.py`.\n'
            '> Edit the troff source and regenerate; `tests/test_man_page.py`\n'
            '> fails while this file disagrees with it.\n'
            '\n'
            f'*{footer}*\n'
            '\n'
        )

    def _do_TH(self, args: list[str], index: int, lineno: int) -> int:
        if len(args) < 2:
            raise UnsupportedTroff(f'line {lineno}: .TH needs a name and a section')
        keys = ('name', 'section', 'date', 'source', 'manual')
        self.title = {k: plain(expand(v, 'R', lineno)) for k, v in zip(keys, args)}
        return index + 1

    def _do_SH(self, args: list[str], index: int, lineno: int) -> int:
        self.item_depth = 0
        name = plain(expand(' '.join(args), 'R', lineno))
        self.sections.append(name)
        self.blank()
        self.out.append(f'## {name}')
        return index + 1

    def _do_SS(self, args: list[str], index: int, lineno: int) -> int:
        self.item_depth = 0
        name = plain(expand(' '.join(args), 'R', lineno))
        self.sections.append(name)
        self.blank()
        self.out.append(f'### {name}')
        return index + 1

    def _do_PP(self, args: list[str], index: int, lineno: int) -> int:
        self.item_depth = 0
        return index + 1

    def _do_IP(self, args: list[str], index: int, lineno: int) -> int:
        """A continuation paragraph inside the current item.

        Only the no-argument form is used by this page; the form with a bullet
        or a tag would need its own list handling, so it is refused instead of
        being rendered as if it had no tag.
        """
        if args:
            raise UnsupportedTroff(
                f'line {lineno}: .IP with arguments is not supported'
            )
        return index + 1

    # -- tagged paragraphs -------------------------------------------------

    def _tag_line(self, index: int, lineno: int) -> tuple[str, int]:
        """Render the tag that follows a .TP, returning it and the next index."""
        if index >= len(self.lines):
            raise UnsupportedTroff(f'line {lineno}: .TP at end of file')
        raw = self.lines[index].rstrip('\n')
        tag_lineno = index + 1
        if raw.startswith('.'):
            macro, _, rest = raw[1:].partition(' ')
            args = split_args(rest, tag_lineno) if rest.strip() else []
            if macro not in SINGLE_FONT and macro not in ALTERNATING:
                raise UnsupportedTroff(
                    f'line {tag_lineno}: .{macro} cannot be a .TP tag'
                )
            return to_markdown(macro_runs(macro, args, tag_lineno)), index + 1
        return to_markdown(expand(raw, 'R', tag_lineno)), index + 1

    def _do_TP(self, args: list[str], index: int, lineno: int) -> int:
        tag, nxt = self._tag_line(index + 1, lineno)
        self.item_depth = 1
        self.blank()
        self.out.append(f'- {tag}')
        return nxt

    def _do_TQ(self, args: list[str], index: int, lineno: int) -> int:
        """A second tag stacked on the current item.

        Emitted with a trailing backslash, which is a hard line break in GitHub
        markdown, so the two tags stay one item with two signatures.
        """
        if not self.out or not self.out[-1].startswith('- '):
            raise UnsupportedTroff(f'line {lineno}: .TQ outside a .TP item')
        tag, nxt = self._tag_line(index + 1, lineno)
        self.out[-1] = self.out[-1] + '\\'
        self.out.append(f'  {tag}')
        return nxt

    # -- code blocks -------------------------------------------------------

    def _do_EX(self, args: list[str], index: int, lineno: int) -> int:
        if self.item_depth:
            raise UnsupportedTroff(
                f'line {lineno}: .EX inside a .TP item is not supported'
            )
        body: list[str] = []
        cursor = index + 1
        while cursor < len(self.lines):
            raw = self.lines[cursor].rstrip('\n')
            if raw.startswith('.EE'):
                break
            if raw.startswith('.'):
                raise UnsupportedTroff(
                    f'line {cursor + 1}: macro .{raw[1:].partition(" ")[0]} '
                    f'inside .EX is not supported'
                )
            body.append(plain(expand(raw, 'R', cursor + 1)))
            cursor += 1
        else:
            raise UnsupportedTroff(f'line {lineno}: .EX with no .EE')
        self.blank()
        self.out.append('```')
        self.out.extend(body)
        self.out.append('```')
        return cursor + 1

    def _do_EE(self, args: list[str], index: int, lineno: int) -> int:
        raise UnsupportedTroff(f'line {lineno}: .EE without .EX')

    # -- synopsis ----------------------------------------------------------

    def _do_SY(self, args: list[str], index: int, lineno: int) -> int:
        """A synopsis group: `.SY cmd`, options, `.YS`.

        Rendered as a code block rather than bold prose. The man rendering puts
        each group on its own hanging-indented line, and a paragraph of bold
        text with square brackets in it is unreadable in markdown.
        """
        tokens = [plain(expand(' '.join(args), 'R', lineno))]
        cursor = index + 1
        while cursor < len(self.lines):
            raw = self.lines[cursor].rstrip('\n')
            cursor_lineno = cursor + 1
            if raw.startswith('.YS'):
                break
            if not raw.startswith('.'):
                tokens.append(plain(expand(raw, 'R', cursor_lineno)))
                cursor += 1
                continue
            macro, _, rest = raw[1:].partition(' ')
            sy_args = split_args(rest, cursor_lineno) if rest.strip() else []
            if macro == 'OP':
                tokens.append('[' + ' '.join(
                    plain(expand(a, 'R', cursor_lineno)) for a in sy_args) + ']')
            elif macro in SINGLE_FONT or macro in ALTERNATING:
                tokens.append(plain(macro_runs(macro, sy_args, cursor_lineno)))
            else:
                raise UnsupportedTroff(
                    f'line {cursor_lineno}: .{macro} is not supported in a synopsis'
                )
            cursor += 1
        else:
            raise UnsupportedTroff(f'line {lineno}: .SY with no .YS')

        line = ' '.join(t for t in tokens if t)
        wrapped = wrap(line, SYNOPSIS_WIDTH)
        rendered = [wrapped[0]] + [f'    {part}' for part in wrapped[1:]]

        # Consecutive synopsis groups share one code block.
        if len(self.out) >= 1 and self.out[-1] == '```':
            self.out.pop()
            self.out.extend(rendered)
        else:
            self.blank()
            self.out.append('```')
            self.out.extend(rendered)
        self.out.append('```')
        return cursor + 1

    def _do_YS(self, args: list[str], index: int, lineno: int) -> int:
        raise UnsupportedTroff(f'line {lineno}: .YS without .SY')

    def _do_OP(self, args: list[str], index: int, lineno: int) -> int:
        raise UnsupportedTroff(f'line {lineno}: .OP outside a synopsis')

    # -- links -------------------------------------------------------------

    def _do_UR(self, args: list[str], index: int, lineno: int) -> int:
        if len(args) != 1:
            raise UnsupportedTroff(f'line {lineno}: .UR needs exactly one URL')
        url = plain(expand(args[0], 'R', lineno))
        text: list[str] = []
        cursor = index + 1
        while cursor < len(self.lines):
            raw = self.lines[cursor].rstrip('\n')
            if raw.startswith('.UE'):
                break
            if raw.startswith('.'):
                raise UnsupportedTroff(
                    f'line {cursor + 1}: macros between .UR and .UE '
                    f'are not supported'
                )
            text.append(plain(expand(raw, 'R', cursor + 1)))
            cursor += 1
        else:
            raise UnsupportedTroff(f'line {lineno}: .UR with no .UE')

        trailing = self.lines[cursor].rstrip('\n')[3:].strip()
        label = md_escape(' '.join(text)) or md_escape(url)
        self.pending.append(f'[{label}]({url}){md_escape(trailing)}')
        return cursor + 1

    def _do_UE(self, args: list[str], index: int, lineno: int) -> int:
        raise UnsupportedTroff(f'line {lineno}: .UE without .UR')

    # -- font macros in running text ---------------------------------------

    def _font_macro(self, macro: str, args: list[str], index: int,
                    lineno: int) -> int:
        self.pending.append(to_markdown(macro_runs(macro, args, lineno)))
        return index + 1

    def _do_B(self, a: list[str], i: int, n: int) -> int:
        return self._font_macro('B', a, i, n)

    def _do_I(self, a: list[str], i: int, n: int) -> int:
        return self._font_macro('I', a, i, n)

    def _do_BR(self, a: list[str], i: int, n: int) -> int:
        return self._font_macro('BR', a, i, n)

    def _do_RB(self, a: list[str], i: int, n: int) -> int:
        return self._font_macro('RB', a, i, n)

    def _do_BI(self, a: list[str], i: int, n: int) -> int:
        return self._font_macro('BI', a, i, n)

    def _do_IR(self, a: list[str], i: int, n: int) -> int:
        return self._font_macro('IR', a, i, n)

    def _do_RI(self, a: list[str], i: int, n: int) -> int:
        return self._font_macro('RI', a, i, n)


def render(source: str) -> str:
    """Render one man page's text as markdown."""
    return Renderer(source.splitlines()).run()


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent.parent
    source = Path(argv[1]) if len(argv) > 1 else here / 'man' / 'filemanager.1'
    target = Path(argv[2]) if len(argv) > 2 else source.with_suffix('.md')

    try:
        text = source.read_text(encoding='utf-8')
    except OSError as error:
        print(f'CANNOT RENDER: {source} is unreadable: {error}', file=sys.stderr)
        return 1

    try:
        markdown = render(text)
    except UnsupportedTroff as error:
        # Nothing is written. A partial markdown file that looks finished is
        # worse than no file, because the next reader believes it.
        print(f'CANNOT RENDER {source}: {error}', file=sys.stderr)
        return 2

    try:
        target.write_text(markdown, encoding='utf-8')
    except OSError as error:
        print(f'CANNOT WRITE {target}: {error}', file=sys.stderr)
        return 1

    print(f'{target.name}: {len(markdown.splitlines())} lines from {source.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
