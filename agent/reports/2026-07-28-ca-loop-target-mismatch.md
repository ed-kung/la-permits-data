# CA loop `next_target` vs agent choice mismatch

**Summary:** Run 1 of `run_ca_data_repair_loop.py` correctly printed `next_target=La Quinta, CA` (parquet appearance order). The launched agent instead sorted jurisdictions alphabetically and worked on Avenal. Terminal output was right; agent selection was wrong.

## What happened

The loop computes `next_target` independently via `first_missing_jurisdiction()`, which walks unique `(JURISDICTION, STATE)` pairs in **parquet row order** (`drop_duplicates(keep="first")`) and checks for `agent/scripts/{state}/data_repair_{state}_{city}.py`.

The agent receives a fixed prompt asking it to find that same first missing pair itself. In run 1 (`agent-ac66efeb-…`), the agent sorted with `sort_values(['STATE','JURISDICTION'])` and therefore picked **Avenal** (alphabetical) instead of **La Quinta** (first in sample order).

Positions in `permits_ca_sample.parquet` unique pairs:

| Jurisdiction | Index in parquet order |
| --- | --- |
| La Quinta | 83 |
| Avenal | 245 |

Run 2 then still saw La Quinta as first missing and correctly produced the La Quinta script.

## Implication

`next_target` / `expected_script` in the loop are advisory only; they are not passed into the agent prompt. Agents can diverge when they reinterpret “go down the list.”

## Possible hardening (not implemented)

- Inject the resolved jurisdiction into the prompt each run, or
- Tighten the prompt to require parquet appearance order (no alphabetical sort).
