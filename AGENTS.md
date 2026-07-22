# LA Permits Research Agent

You are a research assistant helping out with data preparation and analysis for the economics research project contained in this repo. This file is a living document to help you get up to speed on the current state of the project.

## Project 

Exploratory analysis of a Los Angeles County building permits dataset. The research focus may narrow over time.

## Stack

- **Python**: use the repo-local `.venv` (`python3 -m venv .venv` then `pip install -r requirements.txt`)
- Default packages: numpy, pandas, matplotlib, pyarrow, scikit-learn (and others as needed)
- **R**: available for econometric / statistical work

## Data paths

Paths are set in `.env` (see `.env.example`):

| Variable | Role |
| --- | --- |
| `RAW_DATA_PATH` | Local directory with the original raw data (**read-only**) |
| `MY_DATA_PATH` | Local directory for intermediate datasets processed by the human user |
| `AGENT_DATA_PATH` | Local directory for files and artifacts stored by the agent |

Never overwrite, modify, or delete anything under `RAW_DATA_PATH`. Write all derived artifacts to `AGENT_DATA_PATH`.

## Main data file(s)

The main data file that we are currently working with is `MY_DATA_PATH/processed_data/dewey_ca_la_county_permits.parquet`.

The data contains permits from jurisdictions in Los Angeles County.

- Shape (verified 2026-07-21): **7,593,533 rows × 117 columns** (~4.7 GB parquet)
- Jurisdiction field: `JURISDICTION` (also has `CITY`, `COUNTY`, date fields, `JOB_VALUE`, status, description, and many typed permit flags)

A current summary of the usability of the data for each jurisdiction is contained in `ROOT_PATH/reports/2026-07-21-data-usability-report.md`.

## Environment notes

- `.venv` is set up; core packages present except `scikit-learn` (not installed yet). No `requirements.txt` in repo currently.

## Repo layout

- `scripts/` — reproducible analysis scripts (created by human user)
- `notebooks/` - exploratory jupyter notebooks by human user
- `reports/` - reports created by human user
- `agent/scripts/` - reproducible analysis scripts created by agent
- `agent/reports/` - post-task summaries of work and findings by agent
- `.cursor/rules/` — agent rules (data protection, workflow, stack)

## Agent conventions

- After finishing a task, write a dated entry under `agent/reports/` (e.g. `diary/YYYY-MM-DD-short-slug.md`).
