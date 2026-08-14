# Naples (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (in parquet appearance order) was **Naples**. DATA is an EnerGov / Civic `Summary` + `Permits`/`Permit Info` payload. Upstream status lagged portal `Application Status` / date stamps on 224 rows (84 null, 140 wrong); `FILE_DATE` was already complete and correct. Repair filled/fixed status fully, filled 30 missing `PERMIT_DATE` values and cleared 22 spurious Inactive issuance stamps, and filled/fixed 83 `FINAL_DATE` values from `Date Finaled`. After repair: STATUS 100%; FILE_DATE 100%; Active/Final PERMIT_DATE 1,725/1,730 (99.7%); Final FINAL_DATE 852/866 (98.4%).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked `(JURISDICTION, STATE)` pairs in first-appearance order. Naples was the first pair without `agent/scripts/fl/data_repair_fl_naples.py`.

Note: site addresses in `Locations.Address` predominantly say Westlake, FL (ZIP 33470). The same EnerGov schema appears in peer city Westlake, but permit numbers do not overlap the Westlake sample. Repair treats the rows as labeled (Naples).

## DATA shape

| Schema | n |
| --- | ---: |
| `energov_permits_issued_finaled` | 763 |
| `energov_permits_issued` | 717 |
| `energov_permits_project_app_date` | 137 |
| `energov_permits_project_issued` | 127 |
| `energov_permits_app_date` | 102 |
| `energov_permits_project_issued_finaled` | 87 |
| `energov_permit_info_issued` | 53 |
| `energov_permit_info_app_date` | 11 |
| `energov_permits_finaled` | 3 |

Canonical sources:

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `Summary["Application Status"]`, with `Date Finaled` / `Issued Date` overrides |
| FILE_DATE | `Summary["Application Date"]` |
| PERMIT_DATE | `Summary["Issued Date"]` (Active/Final only) |
| FINAL_DATE | `Summary["Date Finaled"]` (Final only) |

## Field assessments

### STATUS_NORMALIZED

Before: Active 931; Final 753; In Review 202; null 84; Inactive 30.

After: Final 866; Active 864; In Review 239; Inactive 31; **0 null**.

| Issue | n | Cause |
| --- | ---: | --- |
| null → In Review | 76 | `STATUS_ORIGINAL` was Returned for Correction / Submittals Incomplete / Revision – Upload Documents; never mapped |
| null → Active | 8 | `Permit(s) Issued` left unmapped |
| Active → Final | 101 | `STATUS_ORIGINAL` stuck on permit(s) issued / issued while `Application Status` advanced to Finaled/Closed (and often `Date Finaled` present) |
| In Review → Active | 26 | Portal still showed In Plan Check / Pending / etc., but `Issued Date` already present |
| In Review → Final | 12 | Same lag plus Finaled/Closed / `Date Finaled` |
| In Review → Inactive | 1 | Expired |

Flags: **84 FILLED, 140 FIXED**.

### FILE_DATE

Missing on 0/2,000. Calendar day matches `Application Date` on every row. Flags: **0 FILLED, 0 FIXED**.

### PERMIT_DATE

Missing before: 283. After: 275.

- **FILLED 30:** mostly In Review→Active promotions where `Issued Date` existed but `PERMIT_DATE` was blank; plus a few Active/Final gaps.
- **FIXED 22:** all cleared — Expired/Canceled rows incorrectly carried an issuance stamp; Ideal rule keeps `PERMIT_DATE` only on Active/Final.

Active/Final coverage after repair: **1,725 / 1,730 (99.7%)**. Remaining 5 are `Closed` Final rows with blank `Issued Date` in DATA.

### FINAL_DATE

Missing before: 1,222. After: 1,148.

- **FILLED 75:** Finaled/Closed (or date-promoted Final) rows that had `Date Finaled` but blank `FINAL_DATE` — often the same Active→Final lag cases.
- **FIXED 8:** 7 overwrote stale earlier final dates with current `Date Finaled`; 1 cleared a final stamp on a row remapped to Inactive (Expired).

Final coverage after repair: **852 / 866 (98.4%)**. Remaining 14 are `Closed` with blank `Date Finaled` (no alternate completion field).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 84 | 140 | 84 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 30 | 22 | 283 → 275 |
| FINAL_DATE | 75 | 8 | 1,222 → 1,148 |

Coverage after repair: FILE_DATE 100%; Active/Final PERMIT_DATE 99.7%; Final FINAL_DATE 98.4%. Source chronology quirks retained: 10 rows with Application Date after Issued Date; 1 with Issued Date after Date Finaled.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_naples.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_naples_repaired.parquet`
