#!/usr/bin/env python3
"""Render coverage.xml and test-results.xml as a readable markdown summary.

Ported from CaptureServer's scripts/coverage_summary.py. Standard library only.

Why this exists: pytest prints a coverage table that scrolls past, and the one
number that survives is the total. The per-file breakdown is what shows *where*
the gap is -- and in this project the gap is concentrated, not spread.

Usage:
    coverage_summary.py <coverage.xml> <output.md> [test-results.xml]
"""

import os
import sys
import xml.etree.ElementTree as ET

# Files that are deliberately below full coverage, with the reason. Rendered as
# a dagger next to the name plus a footnote, so a low number reads as a decision
# rather than as neglect -- and so the next person does not re-derive it.
#
# Only claim "covered elsewhere" where that is true. If the honest answer is
# "this should be restructured so it CAN be tested", say that instead.
COVERAGE_NOTES = {
    "gui": (
        "A Tkinter widget tree and a `mainloop()`. Unit-testing widget "
        "construction asserts on the library rather than on this code, so the "
        "shell stays uncovered on purpose. The part that *is* worth testing -- "
        "which selected rows map to which paths -- should be extracted out of "
        "the widget code and tested there; that is tracked in #3, which fixes "
        "the same function. This note should shrink when #3 lands, not grow."
    ),
}


def pct(covered: int, total: int) -> float:
    return covered / total * 100 if total else 0.0


def bar(p: float, width: int = 24) -> str:
    filled = round(p / 100 * width)
    return "`" + "█" * filled + "░" * (width - filled) + "`"


def badge(p: float) -> str:
    if p >= 80:
        return "\U0001f7e2"
    if p >= 60:
        return "\U0001f7e1"
    return "\U0001f534"


def collect_test_counts(junit_path):
    """(tests, failures, errors, skipped) from a JUnit XML, or None.

    Returns None rather than zeros when the file is absent or unparseable --
    "no data" and "zero failures" must not look identical.
    """
    if not junit_path or not os.path.exists(junit_path):
        return None
    try:
        root = ET.parse(junit_path).getroot()
    except ET.ParseError:
        return None
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    total = failures = errors = skipped = 0
    for suite in suites:
        total += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
    return total, failures, errors, skipped


def module_name(filename: str) -> str:
    """'src/db.py' -> 'db'; keeps a subpackage as 'pkg/mod'."""
    name = filename.replace("\\", "/")
    if name.startswith("src/"):
        name = name[len("src/"):]
    if name.endswith(".py"):
        name = name[: -len(".py")]
    return name


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(2)

    coverage_xml, output_path = sys.argv[1], sys.argv[2]
    junit_path = sys.argv[3] if len(sys.argv) > 3 else None

    root = ET.parse(coverage_xml).getroot()

    rows = []
    tot_lines = tot_lines_hit = tot_branch = tot_branch_hit = 0
    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        if filename.endswith("__init__.py"):
            continue
        lines = cls.find("lines")
        if lines is None:
            continue
        n_lines = n_hit = n_branch = n_branch_hit = 0
        for line in lines.findall("line"):
            n_lines += 1
            hits = int(line.get("hits", 0))
            if hits:
                n_hit += 1
            if line.get("branch") == "true":
                # condition-coverage looks like "50% (1/2)"
                cc = line.get("condition-coverage", "")
                if "(" in cc:
                    taken, possible = cc.split("(")[1].rstrip(")").split("/")
                    n_branch += int(possible)
                    n_branch_hit += int(taken)
        rows.append((module_name(filename), n_hit, n_lines, n_branch_hit, n_branch))
        tot_lines += n_lines
        tot_lines_hit += n_hit
        tot_branch += n_branch
        tot_branch_hit += n_branch_hit

    rows.sort(key=lambda r: (-pct(r[1], r[2]), r[0]))

    line_pct = pct(tot_lines_hit, tot_lines)
    branch_pct = pct(tot_branch_hit, tot_branch)

    out = ["# Coverage Report", ""]
    counts = collect_test_counts(junit_path)
    if counts is None:
        out.append("**Tests:** no test-results.xml was readable, so no counts are shown.")
    else:
        total, failures, errors, skipped = counts
        passed = total - failures - errors - skipped
        verdict = "✅ All passed" if failures == errors == 0 else "❌ Failures present"
        out.append(f"**Tests:** {passed}/{total} passed &nbsp;·&nbsp; {verdict}")
    out += ["", "---", "", "## Overall", "",
            "| Metric | Covered | Total | % | &nbsp; |",
            "|--------|--------:|------:|--:|-------|",
            f"| Lines | {tot_lines_hit:,} | {tot_lines:,} | **{line_pct:.1f}%** | {bar(line_pct)} |",
            f"| Branches | {tot_branch_hit:,} | {tot_branch:,} | **{branch_pct:.1f}%** | {bar(branch_pct)} |",
            "",
            "> Lines and branches are reported separately here. `pytest` prints a single "
            "combined figure because `--cov-branch` folds both into one number, so its "
            "total sits between the two above -- the two are not in disagreement, and it "
            "is the combined one that `--cov-fail-under` compares against.",
            "", "---", "", "## By File", "",
            "| File | Lines | Line % | Branches | Branch % |",
            "|------|------:|-------:|---------:|---------:|"]

    noted = []
    for name, hit, lines, bhit, branches in rows:
        lp = pct(hit, lines)
        bp = pct(bhit, branches)
        dagger = ""
        if name in COVERAGE_NOTES:
            dagger = " †"
            noted.append(name)
        out.append(
            f"| {badge(lp)} `{name}`{dagger} | {hit}/{lines} | {lp:.1f}% | "
            f"{bhit}/{branches} | {bp:.1f}% |"
        )

    if noted:
        out += ["", "---", "", "## Coverage notes", "",
                "**†** — intentionally below full coverage; the reason is recorded, "
                "**not** an unexamined gap:", ""]
        for name in noted:
            out.append(f"- **`{name}` †** — {COVERAGE_NOTES[name]}")

    out.append("")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out))
    print(f"  summary : {output_path} ({line_pct:.1f}% lines, {branch_pct:.1f}% branches)")


if __name__ == "__main__":
    main()
