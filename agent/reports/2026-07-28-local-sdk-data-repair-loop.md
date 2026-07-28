# 2026-07-28 — Local SDK CA data-repair loop

Built a local Cursor SDK orchestrator that replaces manually starting a new chat for each CA jurisdiction data-repair pass.

## Summary

`agent/scripts/run_ca_data_repair_loop.py` launches a **fresh local agent per run** with the fixed prompt in `agent/scripts/prompts/ca_data_repair_next.txt`. Each agent picks the first (JURISDICTION, STATE) lacking `agent/scripts/{state}/data_repair_{state}_{city}.py`, repairs it, and writes a report. Runs are sequential so agents do not race on the same “first missing” target. Cloud Automations were not used because they cannot see local `MY_DATA_PATH`.

## How to run

1. Install (already done in `.venv` for this machine):

```bash
.venv/bin/pip install cursor-sdk
```

2. Set a Cursor user API key ([Dashboard → Integrations](https://cursor.com/dashboard/integrations)):

```bash
export CURSOR_API_KEY=cursor_...
# or add CURSOR_API_KEY=... to .env (see .env.example)
```

3. Dry-run (no API key; prints next missing jurisdiction):

```bash
.venv/bin/python agent/scripts/run_ca_data_repair_loop.py --dry-run
```

4. Run one or more agents:

```bash
.venv/bin/python agent/scripts/run_ca_data_repair_loop.py --max-runs 1
.venv/bin/python agent/scripts/run_ca_data_repair_loop.py --max-runs 5
```

Optional: `--model cursor-grok-4.5-high` (default: Cursor Grok 4.5 High) or `CURSOR_MODEL`; `--skip-exhaustion-check` to always send the prompt even if the orchestrator thinks the queue is empty.

Keep the machine awake while the loop runs (local agents stop if the laptop sleeps).

## Verification

- `cursor-sdk==1.0.24` installed in `.venv`.
- `--dry-run` succeeded: resolved `MY_DATA_PATH`, parquet path, and next target **Visalia, CA** → `agent/scripts/ca/data_repair_ca_visalia.py` (missing).
- Full `--max-runs 1` agent launch was **not** executed in this session because `CURSOR_API_KEY` was unset. After exporting a key, run step 4 above once to confirm an agent starts.

## Artifacts

- [`agent/scripts/prompts/ca_data_repair_next.txt`](../scripts/prompts/ca_data_repair_next.txt) — fixed repair prompt
- [`agent/scripts/run_ca_data_repair_loop.py`](../scripts/run_ca_data_repair_loop.py) — orchestrator
- [`.env.example`](../../.env.example) — documents `CURSOR_API_KEY` / `CURSOR_MODEL`
