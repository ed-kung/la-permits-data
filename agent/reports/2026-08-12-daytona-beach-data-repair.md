# Daytona Beach (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Daytona Beach was first. DATA splits roughly evenly between Accela IMS (`Permit` / `ViewMilestones`, 1,047 rows) and a civic eTRAKiT portal extract (`permit_info`, 953 rows). The dominant defect was IMS Final rows missing `FINAL_DATE` despite a populated `ViewMilestones.Finaled` (≈700 fills). Status repair filled all 16 nulls (mostly unmapped Approved Fees Pending) and fixed 19 stale labels where Milestone had advanced past `STATUS_ORIGINAL`. After repair, Active/Final have full FILE_DATE coverage, PERMIT_DATE on 100% of Active and 99.0% of Final, and FINAL_DATE on 90.3% of Final (remaining gaps are almost all admin-closed / Finaled shells with no final stamp in DATA).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Daytona Beach, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_daytona_beach.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/daytona_beach_repaired_sample.parquet`

## DATA schema

| INFERRED_SCHEMA prefix | n | Notes |
| --- | ---: | --- |
| `ims_full_*` | 1,043 | Permit + ViewMilestones + Contacts/Charges/Review/Inspection |
| `ims_*` / `ims_basic_*` | 4 | thinner IMS scrapes |
| `civic_*` | 953 | permit_info / search_data / site_info portal extract |

Content suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`) reflect whether application, issuance, and final stamps are present in DATA.

Canonical mappings:

| Field | IMS source | Civic source |
| --- | --- | --- |
| STATUS_NORMALIZED | `Permit.Milestone` | `permit_info.PermitStatus` |
| FILE_DATE | `ViewMilestones.Created` | `PermitAppliedDate` |
| PERMIT_DATE | `Issued` (fallback `Approved`) | `PermitIssuedDate` (fallback `PermitApprovedDate`) |
| FINAL_DATE | `Finaled` (fallback `Closed`) | `PermitFinaledDate` |

`APPROVED` is issuance-gated: Active only when an issued/approved date exists, otherwise In Review.

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,535; Inactive 287; Active 120; In Review 42; **null 16**.

- All 16 nulls were IMS rows whose `STATUS_ORIGINAL` was `approved fees pending` (unmapped upstream). Milestone usually still said Approved Fees Pending → **In Review**; a few had already moved to Finaled / Expired / Issued and were filled from Milestone.
- **19 FIXED** from STATUS_ORIGINAL lag vs live Milestone (e.g. `issued`→Finaled, `under review`→Issued/Finaled, `expired`→Finaled/Issued).
- Civic rows already matched `PermitStatus` (0 status changes).

After: Final 1,549; Inactive 286; Active 117; In Review 48; **0 missing**.

### FILE_DATE

Ideal: populated for all records.

- Nearly all rows already matched Created / PermitAppliedDate.
- **1 FILLED** (IMS Created present, FILE_DATE null).
- **0 FIXED.**
- Remaining: **1** civic In Review row with blank `PermitAppliedDate` — not inventable from DATA.

Coverage after repair: Active / Final / Inactive 100%; In Review 47/48 (97.9%).

### PERMIT_DATE

Ideal: populated for Active and Final.

- **58 FILLED** from Issued / Approved when missing (including Inactive with prior issuance).
- **2 FIXED** — cleared Issued stamps on In Review (`hold`, `approved fees pending`) that should not carry PERMIT_DATE.
- Remaining Active/Final gap: **15 Final** (mostly ADMIN CLOSED / Closed shells with no Issued or Approved).

Coverage after repair: Active 117/117 (100%); Final 1,534/1,549 (99.0%); In Review 0/48; Inactive 176/286 (61.5%).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 1,292 missing overall; IMS Final rows systematically lacked FINAL_DATE even when `ViewMilestones.Finaled` was present (scrape/normalize miss).
- **705 FILLED** almost entirely from IMS `Finaled` (plus a few Closed fallbacks on admin-close Final rows).
- **15 FIXED** — cleared non-Final FINAL_DATE (12 Inactive Denied/close stamps, 3 Active).
- Remaining Final without FINAL_DATE (**151**): ADMIN CLOSED (73 civic + 47 IMS), Finaled without Finaled/Closed stamp (17 IMS + 8 civic), and a handful of Closed / Administratively Closed / Completed shells.

Coverage after repair: Final 1,398/1,549 (90.3%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 16 | 19 | 16 → 0 |
| FILE_DATE | 1 | 0 | 2 → 1 |
| PERMIT_DATE | 58 | 2 | 229 → 173 |
| FINAL_DATE | 705 | 15 | 1,292 → 602 |

Root cause of the large FINAL_DATE gap: IMS payloads carry completion in `ViewMilestones.Finaled`, but the upstream pipeline left FINAL_DATE null for those rows. Admin-closed Final records often have no completion stamp at all, so they remain missing after repair by design.
