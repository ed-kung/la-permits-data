# Leon County (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Leon County was first. Its DATA is a Tallahassee/Leon shared portal payload (`Detail` / `Contacts` / `Inspections`, optionally `Subtrades` or a `Date` index). Upstream left 91 `Current Status` values unmapped and mislabeled 59 `COMPLIED` code-enforcement cases as In Review (plus 3 `CONDITIONAL` LUCC rows as Final). More importantly, whenever `Status Date` was parseable it was copied into **both** PERMIT_DATE and FINAL_DATE — but DATA has no separate issue-date field, so Status Date is only a valid issuance proxy for Active rows and a valid completion proxy for Final rows. Repair fills all statuses, clears spurious PERMIT/FINAL copies, and fills 45 FINALED finals from passed final inspections when Status Date is `Unavailable`. After repair: Active/Final have 100% FILE_DATE; Active 88.0% PERMIT_DATE; Final 95.0% FINAL_DATE; non-Final FINAL_DATE is empty.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Leon County, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_leon_county.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/leon_county_repaired_sample.parquet`

## DATA schema

All records share the portal `Detail` block. Originating jurisdiction is mixed (`City of Tallahassee` 1,460; `Leon County` 540). Optional top-level keys produce the INFERRED_SCHEMA variants below.

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `tlhportal_subtrades_insp_applied_status` | 604 | Subtrades + inspections + Applied/Status dates |
| `tlhportal_insp_applied_status` | 524 | Inspections + both dates |
| `tlhportal_noinsp_applied_status` | 320 | No inspections; both dates |
| `tlhportal_dateidx_insp_applied_status` | 143 | Top-level `Date` index + inspections |
| `tlhportal_dateidx_noinsp_applied_status` | 111 | `Date` index, no inspections |
| `tlhportal_noinsp_applied` | 104 | Status Date `Unavailable` |
| `tlhportal_subtrades_noinsp_applied_status` | 90 | Subtrades, no inspections |
| `tlhportal_subtrades_insp_applied` | 47 | Subtrades + insp; Status Date unavailable |
| `tlhportal_insp_applied` | 45 | Inspections; Status Date unavailable |
| `tlhportal_subtrades_noinsp_applied` | 12 | Subtrades only; Status Date unavailable |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Detail.Current Status` |
| FILE_DATE | `Detail.Applied Date` |
| PERMIT_DATE | `Detail.Status Date` **only when status is Active** (no Issue date in DATA) |
| FINAL_DATE | `Detail.Status Date` when Final; else latest Approved/`Y` final-ish `Inspections[].Date` |

## Field assessments

### STATUS_NORMALIZED

91 missing; 62 incorrect.

Upstream mapped only the common codes (`COMPLETE`/`CLOSED`/`FINALED`/`ISSUED`/`EXPIRED`/…). Everything else stayed null. Two systematic mislabels: `COMPLIED` (code-enforcement closed) → In Review, and `CONDITIONAL` (LUCC) → Final while sibling `CONDITIONAL APPROVAL` was already In Review.

**91 FILLED** (largest):

| DATA.Current Status | → | n |
| --- | --- | ---: |
| INVOICED2 | In Review | 16 |
| NOC HOLD | Active | 15 |
| CERTOFOCC | Final | 12 |
| PLANS REVIEW | In Review | 8 |
| ELIGIBLE | In Review | 6 |
| CEB FINDING / CEB LIEN / Code Enforcement Board Finding | Inactive | 8 |
| ROW_ISSUED / ISSUED REDACTED / APPROVED NOTIFY(IED) / CITYWRKS | Active | 7 |
| FINAL INSPECTION COMPLETED | Final | 2 |
| Other review / violation / client-action codes | In Review / Inactive | 17 |

**62 FIXED:** 59 `COMPLIED` In Review → Final; 3 `CONDITIONAL` Final → In Review.

After repair: Final 1,470; Active 242; Inactive 166; In Review 122; null 0.

### FILE_DATE

Ideal: populated for all records. **Already correct** — 0 missing; every FILE_DATE matches `Detail.Applied Date` at day resolution. No FILLED/FIXED.

### PERMIT_DATE

Ideal: populated for Active and Final.

DATA contains **no Issue / Issued / Approval date key**. Upstream set PERMIT_DATE = Status Date whenever Status Date was parseable (1,792 rows), including Final / In Review / Inactive where Status Date is a completion, fee, or expiry stamp — not issuance.

| Action | n |
| --- | ---: |
| FIXED (cleared spurious Status/Applied copies on non-Active) | 1,579 |
| FILLED | 0 |

Active rows that already had PERMIT_DATE = Status Date were left unchanged (correct under the Active-only rule). **29 Active** rows still lack PERMIT_DATE (`ISSUED`/`APPROVED`/`RENEWED` with Status Date `Unavailable` and no alternate issue source). **All Final** PERMIT_DATEs are cleared — not inventable from DATA.

Coverage after repair: Active 213/242 (88.0%); Final 0/1,470.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

Before repair, FINAL_DATE mirrored PERMIT_DATE (same Status Date copy), so 191 Active + 130 In Review + 107 Inactive carried a false final date. Among Final, Status Date was a sound completion stamp when present; 119 Final rows had Status Date `Unavailable`.

| Action | n |
| --- | ---: |
| FILLED from passed final inspection (FINALED, Status Date unavailable) | 45 |
| FIXED (cleared non-Final Status Date copies) | 440 |

**73 Final** rows still miss FINAL_DATE: mostly legacy `CERTIFICATE OF COMPLETION` / `CLOSED` / `CERTIFICATE OF OCCUPANCY` with Status Date `Unavailable` and inspection histories that are all `Not Approved` (or no inspections). Not safely fillable.

Coverage after repair: Final 1,397/1,470 (95.0%); Active/In Review/Inactive FINAL_DATE all empty.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 91 | 62 | 91 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 1,579 | 208 → 1,787 |
| FINAL_DATE | 45 | 440 | 208 → 603 |

Main corrective action is removing the Status Date double-load from PERMIT_DATE/FINAL_DATE and applying it only where the current status makes that date meaningful. Status gaps are fully closed from `Current Status`. True issuance dates for Final (and for Active rows with `Unavailable` Status Date) are not present in this portal JSON.
