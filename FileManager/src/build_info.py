"""What this copy of FileManager was built from.

This file holds the **unbuilt** answer. `scripts/stamp_build_info.py` writes a
replacement into the copy of `src/` that `scripts/build-pyz.sh` archives, so a
bundle carries the commit it was built from and a source checkout does not
pretend to.

`COMMIT is None` is the signal "this is not a build". It is None rather than an
empty string or a row of zeros on purpose: a zero hash is a *value*, and a value
gets printed, compared, and believed. The same reasoning as `UniquenessUnknown`
in `db.py` (#41) -- "could not determine" is not an answer dressed up as one.

**Data only.** Every line of this module is overwritten at build time, so no
logic may live here or it would exist in two versions that drift. The formatting
and the live-git fallback are in `src/version.py`.
"""

COMMIT: str | None = None
BUILD_TIME: str | None = None
DIRTY: bool | None = None
