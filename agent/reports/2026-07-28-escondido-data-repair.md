# Escondido (CA) data repair

**Summary:** Assessed Escondido's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_escondido.py`. Escondido uses a flat portal scrape whose only date field is `Applied`. The repair fills all 142 missing statuses (`PRE-INTAKE` / `PAYMNT_DU` / `PLAN_APPR` → In Review). FILE_DATE already matches `Applied` wherever present (96.0% coverage). PERMIT_DATE and FINAL_DATE are null for every row and cannot be filled — DATA has no issuance or finaled stamps.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Escondido, CA**.

## DATA schema

All 2,000 rows have DATA. Top-level keys are identical across the sample:

`Address`, `Applicant/Owner/Contractor`, `Applied`, `Parcel`, `Permit Description`, `Permit Number`, `Permit Type`, `Status`, `license number`

Content variants (`INFERRED_SCHEMA`):

| Schema | N | Notes |
| --- | --- | --- |
| `portal_in_review` | 1,257 | Pre-issuance Status with parseable Applied |
| `portal_issued` | 579 | Status == ISSUED, Applied present |
| `portal_no_applied` | 79 | Applied blank |
| `portal_finaled` | 45 | FINALED / CLOSED with Applied |
| `portal_inactive` | 40 | Status == N/A with Applied |

Canonical mappings from DATA:

- `Status` → `STATUS_NORMALIZED`
- `Applied` → `FILE_DATE`
- *(none)* → `PERMIT_DATE` / `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: In Review 1,176 / Active 593 / Final 45 / Inactive 44 / missing 142.

`STATUS_ORIGINAL` is always the lowercased `DATA.Status`. Existing non-null mappings are already correct:

| Status | Mapped to | N |
| --- | --- | --- |
| ISSUED | Active | 593 |
| FINALED | Final | 32 |
| CLOSED | Final | 13 |
| PENDING / REVIEW / INCOMPLETE / HOLD | In Review | 1,176 |
| N/A | Inactive | 44 |

Issues:

1. **Missing (142):** `PRE-INTAKE` (70), `PAYMNT_DU` (61), `PLAN_APPR` (11) — all pre-issuance workflow states left unmapped → fill as **In Review**.

Repair performance: **142 FILLED, 0 FIXED**; missing after: **0**.

After: In Review 1,318 / Active 593 / Final 45 / Inactive 44.

Note: the 13 `CLOSED` rows are mostly Investigation / plan-duplication shells. They remain Final to match the existing sample mapping; DATA provides no alternate signal.

### FILE_DATE

Before: 79 missing. Where both present, FILE_DATE matches `Applied` exactly (1,921/1,921). The 79 gaps are blank `Applied` strings (across PENDING, ISSUED, REVIEW, PRE-INTAKE, N/A, PAYMNT_DU) with no other date field in DATA.

Repair: **0 FILLED, 0 FIXED**. Coverage remains **1,921 / 2,000 (96.0%)**.

### PERMIT_DATE

Before: **2,000 missing** (100%). DATA has no Issue / Issued / Approved date. Active (593) and Final (45) rows therefore cannot meet the ideal of a populated PERMIT_DATE.

Repair: **0 FILLED, 0 FIXED**. Active/Final PERMIT_DATE coverage after repair: **0%**.

### FINAL_DATE

Before: **2,000 missing** (100%). DATA has no Finaled / Closed / Completion date. All 45 Final rows (`FINALED` 32 + `CLOSED` 13) lack a completion stamp.

Repair: **0 FILLED, 0 FIXED**. Final FINAL_DATE coverage after repair: **0%**.

## Repair script

`agent/scripts/ca/data_repair_ca_escondido.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: direct map from `DATA.Status` (`FINALED`/`CLOSED`→Final; `ISSUED`→Active; `PENDING`/`REVIEW`/`INCOMPLETE`/`HOLD`/`PRE-INTAKE`/`PAYMNT_DU`/`PLAN_APPR`→In Review; `N/A`→Inactive). FILE_DATE synced from `Applied` when present. PERMIT_DATE / FINAL_DATE left unchanged (no source fields).

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 142 | 0 | 142 | 0 |
| FILE_DATE | 0 | 0 | 79 | 79 |
| PERMIT_DATE | 0 | 0 | 2,000 | 2,000 |
| FINAL_DATE | 0 | 0 | 2,000 | 2,000 |

### Coverage after repair

| Check | Result |
| --- | --- |
| FILE_DATE populated | 1,921 / 2,000 (96.0%) |
| PERMIT_DATE on Active | 0 / 593 (0.0%) |
| PERMIT_DATE on Final | 0 / 45 (0.0%) |
| FINAL_DATE on Final | 0 / 45 (0.0%) |
| STATUS_NORMALIZED missing | 0 |

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_escondido.py`
- Report: `agent/reports/2026-07-28-escondido-data-repair.md`
