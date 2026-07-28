# Simplify CA data-repair loop

**Summary:** Removed jurisdiction selection from `run_ca_data_repair_loop.py`. The looper now only launches the fixed prompt `n` times sequentially; each agent picks the next missing jurisdiction itself.

## Changes

- Dropped `first_missing_jurisdiction`, slug/path helpers, and related parquet lookups.
- Removed `--skip-exhaustion-check` and the per-run `next_target` / `expected_script` printing.
- `--dry-run` now only prints run config (repo, model, max_runs, prompt) without launching agents.
- Staging of repair scripts/reports after each finished run is unchanged.

## Artifact

- `agent/scripts/run_ca_data_repair_loop.py`
