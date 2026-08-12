# Ormond Beach (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script after Westlake was **Ormond Beach** (2,000 rows). DATA is the city-portal family shared with St. Petersburg / Punta Gorda (`detail` + optional `permit_status_detail` / inspections, plus sparse `fees_detail` and `mini_set` shells). Upstream left **1,024** STATUS_NORMALIZED null and copied portal **Permit Date** into PERMIT_DATE (a close-adjacent stamp on Final rows, not issuance). After repair: status complete (FILLED 1,024 · FIXED 18); PERMIT_DATE aligned to **Issue Date** (FIXED 857); FINAL_DATE filled/fixed from inspections and post-issue Permit Date (FILLED 447 · FIXED 340). Remaining gaps are almost entirely shells with no Issue Date / inspection / close stamp in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in first-appearance order. Existing FL repair scripts covered through Westlake / Palm Springs / Port Orange. **Ormond Beach** was the first without `agent/scripts/fl/data_repair_fl_ormond_beach.py`.

- Sample size: **2,000** records
- Script: `agent/scripts/fl/data_repair_fl_ormond_beach.py`
- Artifact: `$AGENT_DATA_PATH/repaired/permits_fl_ormond_beach_repaired.parquet`

## DATA schemas

| Schema family | n | Notes |
| --- | ---: | --- |
| `permit_status_*` | 976 | `detail` + `permit_status_detail` + inspection blocks |
| `fees_detail_*` | 1,001 | `detail` / fees only (no issue or inspection dates) |
| `mini_set_*` | 23 | `application_status` / address / parcel only (no dates) |

`INFERRED_SCHEMA` further splits by status slug. Largest buckets: `fees_detail_administrative_closure` (969) · `permit_status_closed` (820) · `permit_status_c_o_issued` (87) · `permit_status_permit_printed` (42) · `permit_status_final_inspection_complete` (19).

Canonical source fields:

| Target field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Status for Permit Number`, overridden by terminal `Application Status` (CANCELLED / EXPIRED PERMIT / REVOLKED PERMIT / REJECTED); fees_detail / mini_set use `Application Status` alone |
| FILE_DATE | `Application Date` |
| PERMIT_DATE | `Issue Date` (not portal `Permit Date`) |
| FINAL_DATE | Later of successful FINAL/CO (else non-NOC) inspection date and portal `Permit Date` when strictly after `Issue Date` |

## Field assessments

### STATUS_NORMALIZED

**Before:** null 1,024 · Final 926 · Active 42 · In Review 5 · Inactive 3  
**After:** Final 1,907 · Active 41 · Inactive 31 · In Review 21 · null 0  
Flags: **FILLED 1,024 · FIXED 18**

Upstream mapped only rows with `Status for Permit Number` (`closed`→Final, `c.o. issued`→Final, `permit printed`→Active, `to be issued`/`plan check`→In Review, `permit revoked`→Inactive). Problems:

- **1,001 fees_detail** and **23 mini_set** shells had no permit-status block → null STATUS_NORMALIZED (mostly `ADMINISTRATIVE CLOSURE`).
- **17 CLOSED** rows with Application Status `EXPIRED PERMIT` (14) or `CANCELLED` (3) were labeled Final despite terminal outcomes → Inactive.
- **1 PERMIT PRINTED** + `CANCELLED` Active row → Inactive.

FILLED destinations: Final 998 · In Review 16 · Inactive 10.

### FILE_DATE

**Before/after missing: 23.** Ideal: populated for all records.

- On all 1,977 rows with `Application Date`, FILE_DATE already matched at day resolution — **FILLED 0 · FIXED 0**.
- The **23 mini_set** shells have no date fields in DATA → cannot fill.

One chronology quirk remains: a C.O. ISSUED row with Application Date (1998-01-29) one day after Issue Date (1998-01-28); both stamps are faithful to DATA.

### PERMIT_DATE

**Before missing: 1,024. After missing: 1,099** (net clear of unsupported stamps). Ideal: populated for Active and Final.

Upstream copied portal **Permit Date**, which equals Issue Date on Active (`PERMIT PRINTED`) rows but is a later close/C.O. stamp on most Final rows (only 78/820 CLOSED had Issue Date == Permit Date).

Repairs:

- **782** Active/Final/Inactive values **FIXED** from Permit Date → Issue Date.
- **75** cleared (no Issue Date, or In Review / remapped rows carrying Permit-Date-as-issuance).
- Active coverage after repair: **41 / 41 (100%)**.
- Among `permit_status_*` Finals: **844 / 909 (92.8%)**; the 65 gaps are CLOSED shells with blank Issue Date.
- Overall Final PERMIT coverage is **844 / 1,907 (44.3%)** because **~1,000** fees_detail / mini_set Finals never carry Issue Date.
- In Review correctly ends with **0** PERMIT_DATE.

Flags: **FILLED 0 · FIXED 857**.

### FINAL_DATE

**Before missing: 1,616. After missing: 1,176.** Ideal: populated for Final only.

Upstream FINAL often matched an inspection date inside a list truncated at **8** rows. For `C.O. ISSUED` that produced intermediate (non-certificate) dates; the true close/C.O. stamp is portal **Permit Date** (after Issue Date).

Repairs:

- Prefer the later of inspection-derived success dates and Permit Date when Permit Date is strictly after Issue Date (avoids 28 older CLOSED rows where Permit Date precedes Issue Date).
- **All 87 C.O. ISSUED** rows now have FINAL_DATE == Permit Date (**83 FIXED**, 4 already correct).
- **447 FILLED** on Finals that previously lacked FINAL_DATE (mostly CLOSED with usable close stamp / inspections).
- Spurious FINAL on non-Final statuses cleared as part of FIXED.

**After:** Final **824 / 1,907 (43.2%)**; other statuses **0**. Among `permit_status_*` Finals: **824 / 909 (90.6%)**. Remaining Final gaps are fees_detail / mini_set shells (no close stamp) plus **57** CLOSED rows with Issue Date == Permit Date (or Issue > Permit Date) and empty/unusable inspections.

Flags: **FILLED 447 · FIXED 340**.  
PERMIT_DATE > FINAL_DATE inversions after repair: **0**.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1,024 | 18 | 1,024 → 0 |
| FILE_DATE | 0 | 0 | 23 → 23 |
| PERMIT_DATE | 0 | 857 | 1,024 → 1,099 |
| FINAL_DATE | 447 | 340 | 1,616 → 1,176 |

Post-repair coverage vs target rules:

| Rule | Result |
| --- | --- |
| FILE_DATE for all | 1,977 / 2,000 (23 mini_set unfillable) |
| PERMIT_DATE for Active / Final | Active 41/41; Final 844/1,907 (844/909 on permit_status) |
| FINAL_DATE for Final only | 824/1,907 Final; 0 on non-Final |
| Active/Final/Inactive PERMIT = Issue Date | 0 mismatches among 901 rows with Issue Date |

## Not repairable from DATA

- **23 mini_set** rows: no Application / Issue / Permit dates.
- **~1,000 fees_detail** Finals (`ADMINISTRATIVE CLOSURE` etc.): no Issue Date or inspection history → PERMIT_DATE and FINAL_DATE stay missing.
- **CLOSED** Finals with blank Issue Date, or with Issue Date ≥ Permit Date and no usable inspections → issuance / final stamps stay missing.
