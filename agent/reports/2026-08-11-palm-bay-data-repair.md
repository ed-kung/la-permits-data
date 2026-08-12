# Palm Bay (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Palm Bay was first. Its DATA is Accela IMS (`Permit` / `Parcel`, optionally `ViewMilestones`). STATUS_NORMALIZED was wrong or missing on 85 rows (stale Active/In Review vs live Milestone, plus unmapped pending-payment labels). FILE_DATE and PERMIT_DATE were already correct whenever `ViewMilestones` existed; the large missing-date gap is the 1,708 `ims_basic` rows with no milestone dates in DATA. FINAL_DATE gained 45 fills from `Finaled`/`Closed` and 1 clear of a spurious Closed stamp on an Issued permit; among rows with ViewMilestones, Final FINAL_DATE coverage is 154/155 (99.4%).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Palm Bay, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_palm_bay.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/palm_bay_repaired_sample.parquet`

## DATA schema

All records are Accela IMS-shaped (`Permit` + `Parcel` from `ims.palmbayflorida.org`). Variants:

| INFERRED_SCHEMA prefix | n | Notes |
| --- | ---: | --- |
| `ims_basic` | 1,708 | Parcel + Permit only; empty Parcel.status; **no dates** |
| `ims` | 135 | + ViewMilestones (often CustomFields) |
| `ims_full` | 157 | + Contacts/Charges/Review/Inspection |

Content suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`, `_status_only`) reflect which of Created/Submitted, Issued, Finaled/Closed are populated.

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Permit.Milestone` |
| FILE_DATE | `ViewMilestones.Created` (fallback `Submitted`) |
| PERMIT_DATE | `ViewMilestones.Issued` |
| FINAL_DATE | `ViewMilestones.Finaled`, else `Closed` |

`PermitApprovedDate` / `ViewMilestones.Approved` is intentionally **not** used as PERMIT_DATE (plan approval ≠ issuance).

## Field assessments

### STATUS_NORMALIZED

43 missing; most non-null rows already matched Milestone. **43 FILLED + 42 FIXED** (0 missing after):

| Action | Before → After | Milestone | n |
| --- | --- | --- | ---: |
| FIXED | Active → Final | Finaled | 16 |
| FILLED | null → In Review | Submitted - Pending Payment | 15 |
| FILLED | null → In Review | Submitted - Pending Site Visit | 7 |
| FILLED | null → In Review | Approved - Pending Payment | 7 |
| FIXED | In Review → Inactive | Withdrawn | 6 |
| FIXED | Active → Final | Certificate of Occupancy | 5 |
| FILLED | null → In Review | Approved Fees Pending | 5 |
| FIXED | In Review → Final | Finaled | 4 |
| FIXED | Active → In Review | Approved (no Issued) | 3 |
| FIXED | In Review → Active | Issued | 3 |
| FILLED | null → In Review | Under Review - Revisions / Approved Pending Payment | 6 |
| FIXED | Active → Inactive | Expired / Expired - Delinquent | 3 |
| other fills/fixes | — | Issued / Withdrawn / Approval Pending / etc. | 5 |

Cause: upstream `STATUS_ORIGINAL` lagged live `Permit.Milestone`, and several pending-payment / revision milestones were never mapped. After repair: Final 1,620; Inactive 160; In Review 111; Active 109.

### FILE_DATE

Ideal: populated for all records.

- All 292 rows with ViewMilestones already have FILE_DATE equal to Created (and to Submitted when they agree). **0 FILLED / 0 FIXED.**
- Created is preferred over Submitted because Submitted is sometimes rewritten later (e.g. pending-payment completeness) while Created stays the application stamp.
- **1,638 missing** remain on `ims_basic` rows with no date fields in DATA — not inventable.

Coverage after repair: Active 37.6%; Final 13.3%; In Review 63.1%; Inactive 21.9% (driven by which rows have ViewMilestones).

### PERMIT_DATE

Ideal: populated for Active and Final.

- When `Issued` is present (205 rows), PERMIT_DATE already matched at day resolution — **0 FILLED / 0 FIXED.**
- Among ViewMilestones rows after status repair: Active 40/40; Final 151/155; In Review 0/70; Inactive 14/27.
- Remaining Final gaps with VM: 3 Closed + 1 Completed with Approved but no Issued (Approved not used as issuance).
- **1,640+ Active/Final** still missing PERMIT_DATE overall because `ims_basic` has no Issued date.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: many Final rows (esp. Certificate of Occupancy / Finaled) had null FINAL_DATE despite `ViewMilestones.Finaled`; Completed rows already matched `Closed`.
- **45 FILLED** from Finaled/Closed after status alignment.
- **1 FIXED**: Issued row BL25-06643 carried a Closed stamp as FINAL_DATE → cleared.
- Remaining among VM Final: **1** Certificate of Occupancy (BL04-02597) with neither Finaled nor Closed.
- Vast majority of Final rows are `ims_basic` without any final date source → stay missing.

Coverage after repair: Final 203/1,620 (12.5% overall; **99.4%** of Final rows that have ViewMilestones); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 43 | 42 | 43 → 0 |
| FILE_DATE | 0 | 0 | 1,638 → 1,638 |
| PERMIT_DATE | 0 | 0 | 1,727 → 1,727 |
| FINAL_DATE | 45 | 1 | 1,841 → 1,797 |

Main limitation: 85% of the sample is a thin Parcel/Permit scrape without ViewMilestones, so dates cannot be repaired from DATA for those rows. Status can still be corrected from `Permit.Milestone` on every row.
