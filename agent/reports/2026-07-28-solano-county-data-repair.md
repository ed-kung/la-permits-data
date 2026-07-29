# Solano County (CA) data repair

**Summary:** Assessed Solano County's 2,000-row sample and wrote `agent/scripts/ca/data_repair_ca_solano_county.py`. Solano uses an Accela Citizen Access portal payload (`tasks` + `search_data` + top-level `status`/`date`). The repair fills 10 missing statuses and fixes 11 stale ones, brings 6 FILE_DATEs forward to earlier Application Intake Accepted marks, corrects 44 PERMIT_DATEs that used Ready-to-Issue dates instead of Issued (and clears 5 spurious In Review permits), fills 34 FINAL_DATEs on Case Closed / Closed / Completed shells, fixes 1 amendment-cycle FINAL earlier than Issued, and clears 6 spurious FINAL_DATEs on non-Final rows. After repair, FILE_DATE is 100% populated and no non-Final row carries FINAL_DATE. Remaining Active/Final PERMIT and Final FINAL gaps lack Issued / final-inspection evidence in DATA.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Solano County, CA**.

## DATA schema

All 2,000 rows have DATA and share the same Accela portal key set (`address`, `conditions`, `contacts`, `date`, `details`, `fees_details`, `inspections`, `record_type`, `search_data`, `status`, `tasks`, …). Content variants (INFERRED_SCHEMA):

| Schema | N | Notes |
| --- | --- | --- |
| `portal_application_only` | 1,155 | Top-level / intake dates; no Issued or final evidence |
| `portal_issued_finaled` | 535 | Dated Issued + finaling mark |
| `portal_issued` | 233 | Issued present, no finaling date |
| `portal_final_insp_only` | 77 | Final evidence without Issued |

Canonical mappings from DATA:

- `DATA.status` / `search_data.Status` (+ Issued workflow upgrade) → `STATUS_NORMALIZED`
- Earliest of `DATA.date` / `search_data.Date` / Application Intake Accepted* → `FILE_DATE`
- Earliest Permit Issuance / Review and Permit Issuance / License Issuance `Issued` / `Permit Issued` / `Issued w/Supp Conditions` → `PERMIT_DATE`
- Earliest Inspections `Final - No C of O` / `Final - C of O` (prefer on/after Issued; fallback Final CO Issued, Inspection Passed/Completed/Approved/Final-*, Incident Status Closed, complaint Complete/Closed) → `FINAL_DATE`

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,162 / Active 344 / Inactive 271 / In Review 213 / missing 10.

Issues:

1. **Missing (10):** 4 null-status Enforcement Complaints (TBD only → In Review); 1 `Plans Approved - Fees Due` → In Review; 1 `Approved for Business License` → Active; 4 terminal denials (`Development Not Allowed`, `Not Allowed in Zone`, `Void Complaint`, `Inactive-Less than Reportable`) → Inactive.
2. **Incorrect / stale (11):**
   - 5 `C of O Pending` and 1 `On Hold` with dated Issued left In Review → Active.
   - 2 `Approved` without issuance left Active → In Review.
   - 1 `Complied` (enforcement In Compliance mark) left In Review → Final.
   - 1 `Suspended` → Inactive; 1 `Delinquent` → Inactive.

Repair performance: **10 FILLED, 11 FIXED**; missing after: **0**.

After: Final 1,163 / Active 348 / Inactive 277 / In Review 212.

### FILE_DATE

Before: 0 missing. All 2,000 FILE_DATE values match `DATA.date`. Six rows have Application Intake `Accepted*` earlier than `DATA.date` (1–37 days).

Repair: **0 FILLED, 6 FIXED**. Coverage remains 100%.

### PERMIT_DATE

Before: 1,221 missing. Where an Issued mark exists, 724 PERMIT_DATEs matched and **44 used Ready to Issue / Comments Coordination dates** a few days (up to ~200) before the real Issued stamp. Eleven In Review / Inactive rows carried Ready-to-Issue-era PERMIT_DATEs without an Issued mark.

Repair: **0 FILLED, 49 FIXED** (44 corrected to Issued; 5 cleared on In Review without issuance). Missing after: 1,226 (net +5 clears).

Remaining Active/Final gap: **816** (Finaled 558, Active 104, Issued 77, Closed/Case Closed/Completed/etc.) — all lack a dated Issued mark in DATA (Permit Issuance TBD or empty). Active coverage after repair: **160 / 348 (46.0%)**; Final: **535 / 1,163 (46.0%)**. In Review PERMIT_DATE: **0**.

### FINAL_DATE

Before: 1,438 missing. 556 Final rows already had FINAL_DATE matching Inspections `Final - No/C of O` (plus a few Inspection Completed marks). **606 Final rows** lacked FINAL_DATE; **34** of those have fillable Incident Status Closed / complaint Complete / Inspection Passed evidence (mostly Case Closed General Complaints). **6 non-Final rows** carried FINAL_DATE (5 C of O Pending with `Final - C of O`; 1 Expired with `Final - No C of O`). One Finaled amendment cycle had FINAL_DATE from an older Final stamp (2014) while Issued was 2017 (a same-day Final mark also exists).

Repair: **34 FILLED**, **7 FIXED** (6 cleared on non-Final; 1 amendment-cycle Final moved to on/after Issued).

Final coverage after repair: **590 / 1,163 (50.7%)**. No spurious FINAL_DATE remains on Active / In Review / Inactive. Chronology: 0 PERMIT&lt;FILE, 0 FINAL&lt;PERMIT.

## Repair script

`agent/scripts/ca/data_repair_ca_solano_county.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic: Inactive labels sticky; Finaled/Closed/Completed/Case Closed/In Compliance/Complied → Final; Issued/Active/In Violation/C of O Pending → Active; dated Issued promotes remaining In Review → Active; Approved without issuance stays In Review.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | --- | --- | --- | --- |
| STATUS_NORMALIZED | 10 | 11 | 10 | 0 |
| FILE_DATE | 0 | 6 | 0 | 0 |
| PERMIT_DATE | 0 | 49 | 1,221 | 1,226 |
| FINAL_DATE | 34 | 7 | 1,438 | 1,410 |

### Artifact

`AGENT_DATA_PATH/repaired/permits_ca_solano_county_repaired.parquet`
