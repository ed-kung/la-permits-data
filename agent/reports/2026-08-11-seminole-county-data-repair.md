# Seminole County (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Seminole County was first. Its DATA is a sparse portal payload (`fees` / `detail` / `fees_total`) whose only lifecycle signal is `detail.Application`, with `detail.Application Date` as the sole date. STATUS_NORMALIZED (and STATUS_ORIGINAL) were null on all 2,001 rows — upstream never mapped `Application` — and all were FILLED (Final 1,490; Active 262; Inactive 164; In Review 85). FILE_DATE already matched Application Date for every row. DATA has no issue or finalization timestamps, so PERMIT_DATE and FINAL_DATE remain fully missing.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Seminole County, FL** (2,001 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_seminole_county.py` (`data_repair`)

## DATA schema

| INFERRED_SCHEMA | n | Application |
| --- | ---: | --- |
| `fees_detail_complete` | 1,067 | PERMIT COMPLETE |
| `fees_detail_issued` | 262 | PERMIT ISSUED |
| `fees_detail_closed` | 212 | CLOSED |
| `fees_detail_co` | 164 | CERTIFICATE OF OCCUPANCY |
| `fees_detail_voided` | 164 | VOIDED |
| `fees_detail_plan_check` | 52 | IN PLAN CHECK |
| `fees_detail_cc` | 47 | CERTIFICATE OF COMPLETION |
| `fees_detail_on_hold` | 16 | ON HOLD |
| `fees_detail_approved` | 16 | APPROVED |
| `fees_detail_in_approval` | 1 | IN APPROVAL |

Every row shares the same top-level key set. Detail keys are fixed (Owner, Address, Parcel ID, Valuation, Application, Application Date/Type/Number, etc.). No inspections, Issue Date, or C.O. date fields.

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `detail.Application` |
| FILE_DATE | `detail.Application Date` |
| PERMIT_DATE | *(none in DATA)* |
| FINAL_DATE | *(none in DATA)* |

Application → normalized: PERMIT COMPLETE / CLOSED / CERTIFICATE OF OCCUPANCY / CERTIFICATE OF COMPLETION → Final; PERMIT ISSUED → Active; IN PLAN CHECK / ON HOLD / APPROVED / IN APPROVAL → In Review; VOIDED → Inactive. APPROVED is treated as pre-issuance (distinct from PERMIT ISSUED; many APPROVED rows still show unpaid fees).

## Field assessments

### STATUS_NORMALIZED

**2,001 missing** (100%). `STATUS_ORIGINAL` is also entirely null — root cause is upstream never reading `detail.Application` (the portal stores status under that key, not `Status` / `Application Status`).

**2,001 FILLED.** 0 FIXED (no prior non-null values to disagree with). All Application strings map; none unmapped.

After repair: Final 1,490; Active 262; Inactive 164; In Review 85.

### FILE_DATE

Ideal: populated for all records.

- Before: **0 missing**. All 2,001 equal `Application Date` at day resolution (range 1990-03-06 – 2025-10-02).
- **0 FILLED / 0 FIXED.** Coverage remains 100% for every status.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Before/after: **2,001 missing**. DATA exposes no Issue Date / Permit Date / paid-on issuance stamp.
- Fee totals are not used as a proxy (unpaid balances appear across Issued, Complete, Voided, and review statuses).
- Coverage after repair: Active 0/262; Final 0/1,490.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before/after: **2,001 missing**. No C.O. Issued, completion date, or inspection history in DATA.
- Final rows (PERMIT COMPLETE / CLOSED / CO / CC) stay without FINAL_DATE. No spurious non-Final FINAL_DATE to clear.
- Coverage after repair: Final 0/1,490; other statuses 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 2,001 | 0 | 2,001 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,001 → 2,001 |
| FINAL_DATE | 0 | 0 | 2,001 → 2,001 |

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_seminole_county.py`
- Repaired sample parquet: `AGENT_DATA_PATH/seminole_county_repaired_sample.parquet`
