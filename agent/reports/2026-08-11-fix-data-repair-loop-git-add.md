# Fix data repair loop `git add` pathspec failure

`run_data_repair_loop.py` failed to stage new repair scripts and reports because `git add` was given a pathspec that matched no files.

## Cause

Staging used these pathspecs:

- `:(glob)agent/scripts/**/data_repair_*.py`
- `:(glob)agent/scripts/data_repair_*.py`  ← matches nothing (scripts live under `{state}/` subdirs)
- `:(glob)agent/reports/*.md`

`git add` exits fatally if **any** pathspec matches zero files, so the empty top-level glob aborted the whole add even when nested scripts and reports existed.

## Fix

In `agent/scripts/run_data_repair_loop.py`:

1. Dropped the obsolete top-level `agent/scripts/data_repair_*.py` glob.
2. `git add` now uses the concrete paths from `git status --porcelain` (candidates), not the globs.

Verified by creating temporary untracked `data_repair_*.py` and report `.md` files, confirming both staged successfully, then removing them.
