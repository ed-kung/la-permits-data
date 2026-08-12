# Davie (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Davie was first. Its DATA is a Logos/TRAKiT-style payload whose lifecycle signal lives in `Permit Summary.StatusValue` (often with an embedded date). STATUS_NORMALIZED was missing on 35 `Permit Expired MM/DD/YYYY` rows (upstream failed to normalize dated expirations) — all FILLED to Inactive. FILE_DATE was almost entirely empty (20/2,001); 694 fills came from earliest non-archival Notes bounded by the status lifecycle date. PERMIT_DATE was already correct for all Active rows and is not inventable for Final (no IssueDate; PaidValue is fee payment). FINAL_DATE gained 6 inspection-based fills; Final coverage is 97.7% after repair.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Davie, FL** (2,001 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_davie.py` (`data_repair`)

## DATA schema

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `logos_completed` | 1,746 | nested keys; Completed with status date or Passed final insp |
| `logos_pending` | 78 | Pending Payment as of … |
| `logos_expired` | 43 | Permit Expired with date |
| `logos_status_only` | 41 | bare `Permit Completed` (no date, no Passed final insp) |
| `logos_expired_bare` | 37 | bare `Permit Expired` |
| `logos_issued` | 35 | Permit Issued on … |
| `logos_created` | 20 | Permit/Application Created |
| `logos_flat_expired` | 1 | flat sibling schema (`Status`, `Paid On`, …) |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `StatusValue` / flat `Status` base text |
| FILE_DATE | Created status date; else earliest non-Microfilm/Historical `Notes` date ≤ lifecycle date |
| PERMIT_DATE | Issued status date only |
| FINAL_DATE | Completed status date; else latest Completed+Pass final-ish inspection |

StatusValue bases → normalized: Completed→Final; Issued→Active; Expired→Inactive; Pending Payment / Created / Application Created→In Review.

## Field assessments

### STATUS_NORMALIZED

**35 missing**, all `Permit Expired MM/DD/YYYY` (including one flat-schema row). Cause: upstream `STATUS_ORIGINAL` keeps the expiration date suffix, so normalization missed them while bare `permit expired` mapped to Inactive.

**35 FILLED → Inactive.** No FIXED rows — every non-null STATUS already matched StatusValue.

After repair: Final 1,787; In Review 98; Inactive 81; Active 35.

### FILE_DATE

Ideal: populated for all records.

- Before: **1,981 missing**. The 20 present rows are all Permit/Application Created and already equal the embedded status date.
- DATA has no ApplyDate field. `Payment Summary.PaidValue` is fee payment (often near issue, sometimes years before final) — not used as FILE_DATE.
- **694 FILLED** from earliest usable Notes date capped by Issued / Completed / Expired / Pending Payment lifecycle date (635 Final, 28 Active, 22 Inactive, 9 In Review).
- Remaining gap: **1,287** rows with no usable Notes (or notes only after the lifecycle date).

Coverage after repair: Active 80.0%; Final 35.5%; In Review 29.6%; Inactive 27.2% (overall 35.7%).

### PERMIT_DATE

Ideal: populated for Active and Final.

- All 35 Active rows already had PERMIT_DATE equal to `Permit Issued on …` — **0 FILLED / 0 FIXED**.
- Final rows never expose an issue date in StatusValue. PaidValue ≤ FINAL on ~1,011 Completed rows but is not a reliable issuance stamp (median Paid→Final gap 134 days; 344 gaps > 1 year) → left missing.
- Coverage after repair: Active 35/35 (100%); Final 0/1,787 (0%).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 1,740/1,787 Final rows had FINAL_DATE; all matched `Permit Completed on …` when that date was present (including 12 historic 1964–1979 completions).
- **47** Final rows were bare `Permit Completed` with null FINAL_DATE.
- **6 FILLED** from latest Completed+Pass final inspection; **41** remain empty (no status date, no Passed final insp).
- No non-Final FINAL_DATE to clear. **0 FIXED.**

Coverage after repair: Final 1,746/1,787 (97.7%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 35 | 0 | 35 → 0 |
| FILE_DATE | 694 | 0 | 1,981 → 1,287 |
| PERMIT_DATE | 0 | 0 | 1,966 → 1,966 |
| FINAL_DATE | 6 | 0 | 261 → 255 |

Post-repair checks (status vs StatusValue map; FILE ≤ PERMIT/FINAL when both present; PERMIT equals Issued status date; FINAL only on Final and equal to Completed status date when present): **0 violations**.

## Artifacts

- Repair function: `agent/scripts/fl/data_repair_fl_davie.py`
- Preview stats: `AGENT_DATA_PATH/davie_repair_stats.json`
