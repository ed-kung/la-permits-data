# Antioch (CA) data repair

**Summary:** Antioch was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Assessed and repaired `STATUS_NORMALIZED`, `FILE_DATE`, `PERMIT_DATE`, and `FINAL_DATE` from Tyler EnerGov and legacy-flat `DATA` JSON. Status is now fully populated (**FILLED 1 · FIXED 315**): 307 Archived rows mis-labeled In Review → Inactive, 8 Active/Issued rows with finalization evidence → Final, and one legacy `wmp2 req'd` null status → In Review. `FILE_DATE` missingness fell from **183 → 0** (**FILLED 183**) by using legacy `ISSUE DATE` as the only available proxy. `PERMIT_DATE` was already correct wherever `IssueDate` / `ISSUE DATE` exists (**0 changes**; 178 remain unfillable, including 22 Active/Final with null IssueDate). `FINAL_DATE` gained **1 FILLED** (Issued→Final with `FinalizeDate`); Final coverage is **945 / 967 (97.7%)**. Remaining Final gaps are all legacy `FINALED` rows with no signoff field.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: **Antioch, CA** (n=2,000)
- Script: `agent/scripts/ca/data_repair_ca_antioch.py` (`data_repair`)

## DATA schema (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `entity_fees` | 1,792 | EnerGov: `entity`, `details`, `fees`, `contacts`, `processing_status` |
| `legacy_flat` | 183 | Tabular scrape: `STATUS`, `ISSUE DATE`, APN/site/contractor (key-set typos vary) |
| `entity_fees_reviews` | 25 | `entity_fees` plus `reviews` / `holds` / `attachments` / `more_info` |

Canonical fields:

| Field | Source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (else `details.PermitStatus` / `STATUS`); override to Final if `PermitStatus=Finaled` or Active with `FinalDate`/`FinalizeDate` |
| `FILE_DATE` | `entity.ApplyDate` / `details.ApplyDate`; legacy: `ISSUE DATE` |
| `PERMIT_DATE` | `entity.IssueDate` / `details.IssueDate` / `ISSUE DATE` |
| `FINAL_DATE` | `entity.FinalDate` / `details.FinalizeDate` |

## Field assessment

### STATUS_NORMALIZED

**Before:** Final 959 · Inactive 466 · In Review 340 · Active 234 · missing 1

Issues:
1. **Archived → In Review (307)** — same mis-mapping seen in Burbank / Huntington Beach. Archived cases (mostly issued 2000–2022, no FinalDate) should be **Inactive**.
2. **Active with FinalDate (7)** — `CaseStatus`/`PermitStatus` still say Active, but `FinalDate`/`FinalizeDate` are set and already copied into `FINAL_DATE`. Treated as **Final**.
3. **Issued vs Finaled (1)** — `CaseStatus=Issued`, `PermitStatus=Finaled`, `FinalizeDate` present, `STATUS_NORMALIZED=Active`. Treated as **Final**.
4. **Legacy `wmp2 req'd` (1)** — null `STATUS_NORMALIZED`; pending-requirement wording → **In Review**.

EnerGov status map used by the repair:

| CaseStatus | STATUS_NORMALIZED |
| --- | --- |
| Finaled, Closed | Final |
| Issued, Active, Approved | Active |
| Pending, In Review, Requires Re-Submittal, Fees Due/Paid, Submitted (- Online), On Hold | In Review |
| Expired, Void, Cancelled, Archived | Inactive |

Legacy: `ACTIVE`/`ISSUED` → Active; `FINALED` → Final; `PENDING` / `wmp2 req'd` → In Review.

**After:** Final 967 · Inactive 773 · Active 226 · In Review 34 · missing 0  
Flags: **FILLED 1 · FIXED 315**

### FILE_DATE

**Before:** 183 missing (9.2%), all on `legacy_flat`.

- EnerGov: every row’s `FILE_DATE` already matches the UTC calendar day of `ApplyDate` (0 mismatches).
- Legacy: no apply/submittal field; only `ISSUE DATE` exists (and already equals `PERMIT_DATE`). Filled `FILE_DATE` from `ISSUE DATE` as a same-day proxy.

**After:** 0 missing.  
Flags: **FILLED 183 · FIXED 0**

### PERMIT_DATE

**Before:** 178 missing (8.9%). Among Active/Final: 22 / 1,193 missing.

- EnerGov: when `IssueDate` is present, `PERMIT_DATE` always matches (0 mismatches, 0 fillable misses).
- Legacy: all 183 rows already have `PERMIT_DATE` = `ISSUE DATE`.
- Unfillable Active/Final misses (15 Active + 7 Final) have `CaseStatus` Issued/Active/Finaled but null `IssueDate` and `Issued=False`.

**After:** still 178 missing (no fillable sources).  
Flags: **FILLED 0 · FIXED 0**  
Active/Final coverage after status repair: **211/226 (93.4%)** Active · **960/967 (99.3%)** Final.

### FINAL_DATE

**Before:** 1,056 missing (52.8%). Among Final: 22 / 959 missing (all legacy).

- EnerGov Finaled/Closed: `FINAL_DATE` already matches `FinalDate`/`FinalizeDate` when present.
- One Issued→Final row had `FinalizeDate` but null `FINAL_DATE` → **FILLED**.
- The 7 Active→Final rows already carried `FINAL_DATE` from `FinalDate`.
- Legacy `FINALED` (22): no final/signoff field → unfillable.
- After repair, no non-Final rows retain `FINAL_DATE`.

**After:** 1,055 missing; Final coverage **945 / 967 (97.7%)**.  
Flags: **FILLED 1 · FIXED 0**

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| `STATUS_NORMALIZED` | 1 | 315 | 1 → 0 |
| `FILE_DATE` | 183 | 0 | 183 → 0 |
| `PERMIT_DATE` | 0 | 0 | 178 → 178 |
| `FINAL_DATE` | 1 | 0 | 1,056 → 1,055 |

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_antioch.py`
- Repaired sample: `AGENT_DATA_PATH/permits_ca_antioch_repaired.parquet`
