# 2026-07-28 — Loop stages repair artifacts (no commit)

## Summary

Updated `agent/scripts/run_ca_data_repair_loop.py` so that after each agent run completes, it `git add`s new or changed repair scripts and reports. It does **not** create a commit; the user commits and pushes manually.

## Behavior

After `run.wait()` returns (success or failure), the orchestrator stages paths matching:

- `agent/scripts/**/data_repair_*.py`
- `agent/scripts/data_repair_*.py` (legacy layout)
- `agent/reports/*.md`

It prints the staged paths. `__pycache__`, the loop script itself, and other unrelated dirty files are left alone.

## Artifacts

- [`agent/scripts/run_ca_data_repair_loop.py`](../scripts/run_ca_data_repair_loop.py)
