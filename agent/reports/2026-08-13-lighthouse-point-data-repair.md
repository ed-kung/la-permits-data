# Lighthouse Point (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **Lighthouse Point**. DATA is a SmartGov community portal payload (`My Project` / `Build Status` / optional `Parcel Number` + `ProjectDescription`). Upstream left 208 statuses null and mislabeled 20 Closed / Expired rows (STATUS_ORIGINAL lagged as `issued` / `ready to issue`). Repair FILLED 200 and FIXED 23 statuses; FILLED 11 PERMIT_DATE and 20 FINAL_DATE values from Issued / Closed. FILE_DATE already matched Submitted on all non-empty rows. After repair: STATUS null 208→8 (empty shells only); FILE_DATE 100% among rows with a status; Active/Final PERMIT_DATE 1,828/1,843 (99.2%); Final FINAL_DATE 1,567/1,738 (90.2%).

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py` in first-seen order. First missing: **Lighthouse Point, FL** → `agent/scripts/fl/data_repair_fl_lighthouse_point.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `smartgov_full` | 1,722 | + `ProjectDescription` (and usually `Parcel Number`) |
| `smartgov_no_desc` | 268 | + `Parcel Number`, no `ProjectDescription` |
| `smartgov_empty` | 10 | SmartGov keyset present; Build Status / Permit Number / Permit Type / My Project dates all blank |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Build Status` (`Expired*` / `DENIED` sticky Inactive; `Closed` → Final; `Issued` → Active; `SENT TO *` / `Ready To Issue` → In Review); else My Project dates (Closed → Final, Issued → Active, Submitted/Created → In Review) |
| FILE_DATE | `My Project.Submitted` (fallback `Created`) |
| PERMIT_DATE | `My Project.Issued` (fallback `Approved`) for Active / Final / Inactive |
| FINAL_DATE | `My Project.Closed` → latest passed Final/COO `Permit Inspections`; Final only |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,707; null 208; Active 62; Inactive 19; In Review 4.

| Build Status | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| Closed | 1,725 | Final 1,705 / Active 19 / In Review 1 | 20 lag mislabels (STATUS_ORIGINAL still `issued` / `ready to issue`) |
| Issued | 51 | Active 42 / null 7 / In Review 2 | 9 unmapped (STATUS_ORIGINAL still department-queue / ready-to-issue) |
| Expired* | 32 | Inactive 13 / null 18 / Active 1 | Partial Expired mapping; 1 still Active |
| DENIED | 6 | Inactive 4 / null 2 | 2 unmapped |
| SENT TO * | 8 | all null | Unmapped department queues |
| Ready To Issue | 1 | In Review 1 | Correct |
| null Build Status | 177 | null 175 / Final 2 | 167 have Permit Type + Submitted; 65 Issued; 11 Closed — recoverable via dates |

**Root causes:**
- **STATUS_ORIGINAL lag:** Live `Build Status` is `Closed` / `Expired*` / `Issued` while `STATUS_ORIGINAL` still says `issued` / `ready to issue` / `sent to …`, so upstream normalization stayed Active / In Review / null.
- **Unmapped queues / DENIED / Expired:** `SENT TO *`, some `DENIED`, and many `Expired: M/D/YYYY` never mapped to STATUS_NORMALIZED.
- **Null Build Status with dates:** Recent shells omit Build Status / Permit Number but carry Submitted / Issued / Closed → should be In Review / Active / Final from dates.
- **Empty shells:** 10 rows carry no status or date signal → not repairable.

**Repair performance:** FILLED 200, FIXED 23; missing 208 → 8. After: Final 1,738; In Review 111; Active 105; Inactive 38; null 8 (`smartgov_empty` only).

### FILE_DATE

Ideal: populated for all records.

- Non-empty (1,990): **0 missing** before/after; all equal `My Project.Submitted` at calendar-day resolution (**0 FILLED / 0 FIXED**).
- Empty shells (10): 8 missing FILE_DATE with no Submitted/Created (2 empty shells already had FILE_DATE from upstream with empty `My Project` — left unchanged).
- Coverage after repair among rows with a status: **100%**.
- One agency-side inversion remains: Submitted `2012-12-06` after Issued `2012-12-05` on PN `12-1403` (not introduced by repair).

### PERMIT_DATE

Ideal: populated for Active and Final.

- Existing values matched `Issued` whenever both present (**0 calendar mismatches**).
- **11 FILLED** on newly Active / Inactive rows that had Issued (or Approved) but blank PERMIT_DATE (Issued BS still in review/null; some Expired shells).
- **15 Final** legacy Closed roofs (mostly 2001) keep blank PERMIT_DATE — Issued/Approved are SmartGov placeholders or out-of-range (`2090` rejected).
- Active 105/105 (100%); Final 1,723/1,738 (99.1%); In Review 0/111; Inactive 15/38.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Where `My Project.Closed` is present, upstream FINAL_DATE already matched (**0 mismatches**).
- **20 FILLED** from Closed on rows reclassified to Final (19 Active→Final, 1 In Review→Final).
- Eleven null-status shells already had FINAL_DATE = Closed; status FILLED to Final so FINAL is retained (not flagged).
- **171 Final** remain without FINAL_DATE: Closed is blank and inspections are present but `Status` is empty (e.g. `ROOFING (view notes)`) — not treatable as passed Final/COO.
- Non-Final FINAL_DATE: 0 after repair. Final coverage 1,567/1,738 (90.2%); among Final with a Closed stamp, 1,565/1,565 (100%).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 200 | 23 | 208 → 8 |
| FILE_DATE | 0 | 0 | 8 → 8 |
| PERMIT_DATE | 11 | 0 | 168 → 157 |
| FINAL_DATE | 20 | 0 | 453 → 433 |

Coverage after repair: FILE_DATE 100% for all non-null statuses; Active/Final PERMIT_DATE 1,828/1,843; Final FINAL_DATE 1,567/1,738. Remaining gaps are empty shells and legacy Closed records without Issued/Closed timestamps (and inspections without pass status).

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_lighthouse_point.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_lighthouse_point_repaired.parquet`
