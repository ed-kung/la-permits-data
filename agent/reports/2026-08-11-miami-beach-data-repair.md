# Miami Beach (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Miami Beach was first. Its DATA is a uniform Tyler EnerGov payload. STATUS_NORMALIZED was missing on 31 rows (Initial / Recertified) and wrong on 88 more (stale Applied / Pending / Initial labeled In Review despite IssueDate; Suspended as In Review; Issued / Applied carrying FinalDate still Active / In Review). FILE_DATE was already complete and correct. PERMIT_DATE gained 12 fills after status upgrades; Active coverage became 100%, while 465 Final rows still lack IssueDate in DATA. FINAL_DATE needed 110 clears of non-Final void/close stamps; Final coverage is 99.1% after repair (11 legacy ZZConverted Closed rows remain empty).

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Miami Beach, FL** (1,998 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_miami_beach.py` (`data_repair`)

## DATA schema

All records are EnerGov-shaped (`entity`, `details`, `contacts`, `fees`, `processing_status`). Variants:

| INFERRED_SCHEMA prefix | n | Notes |
| --- | ---: | --- |
| `energov` | 1,847 | fees present |
| `energov_full` | 151 | + reviews/holds/attachments/more_info |

Content suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`) reflect which of ApplyDate / IssueDate / FinalDate are populated. `processing_status` items use `status` / `description` / `scheduled_date` (results often `Passed`).

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (+ IssueDate / FinalDate overrides for stale labels) |
| FILE_DATE | `ApplyDate` |
| PERMIT_DATE | `IssueDate` |
| FINAL_DATE | `FinalDate` / `FinalizeDate`, else Passed/Approved final inspection |

## Field assessments

### STATUS_NORMALIZED

31 missing (`Initial` ×30, `Recertified` ×1). Remaining rows mostly matched CaseStatus, but several labels lagged the dates/flags in DATA.

**31 FILLED:** Initial → In Review (30); Recertified → Final (1).

**88 FIXED:**

| Before → After | CaseStatus | n | Reason |
| --- | --- | ---: | --- |
| In Review → Active | Applied | 80 | `Issued=true` + IssueDate; CaseStatus never flipped to Issued |
| In Review → Active | Pending | 2 | same |
| In Review → Active | Initial | 1 | same |
| In Review → Final | Applied | 2 | FinalDate present (completed short-term / demo cases) |
| Active → Final | Issued | 1 | FinalDate present (elevator license) |
| In Review → Inactive | Suspended | 2 | suspended issued permits are not In Review |

After repair: Final 1,165; Active 403; In Review 259; Inactive 171. No missing statuses.

### FILE_DATE

Ideal: populated for all records. **Already correct** — 0 missing; every FILE_DATE matches ApplyDate at day resolution. No FILLED/FIXED.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When present, always equaled IssueDate (no incorrect values to overwrite).
- **12 FILLED** after status upgrades to Active (Applied/Pending/Initial with IssueDate but blank PERMIT_DATE).
- Remaining gap: **465 Final** still missing PERMIT_DATE because IssueDate is null and `details.Issued` is false (mostly Closed; also some Finaled and the Recertified / Applied→Final rows without IssueDate). Not inventable from DATA — alternate entity dates (StartDate / OpenedDate / ClosedDate) are also null on these rows.

Coverage after repair: Active 403/403 (100%); Final 700/1,165 (60.1%); In Review 0/259; Inactive 60/171.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 11 Final rows missing FINAL_DATE; 114 non-Final rows had FINAL_DATE equal to FinalDate void/close/license stamps (Void, Abandon, Cancel, Denied, Revoked, Applied, Issued, Recertified-before-fill).
- **0 FILLED** — every Final row that had a usable FinalDate already carried it; inspection fallback did not recover the 11 empties (`processing_status` is null on those ZZConverted Closed permits).
- **110 FIXED** (cleared non-Final FINAL_DATE). Three rows remapped into Final already had FINAL_DATE, so they needed no fill.
- Remaining: **11 Final** Closed `ZZConverted - Converted Permits` with no FinalDate, ClosedDate, CompleteDate, or inspections.

Coverage after repair: Final 1,154/1,165 (99.1%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 31 | 88 | 31 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 12 | 0 | 847 → 835 |
| FINAL_DATE | 0 | 110 | 734 → 844 |

Missing FINAL_DATE rose because 110 non-Final void/close stamps were cleared; that is intentional. Active PERMIT_DATE coverage is complete; Final PERMIT_DATE and the 11 converted FINAL_DATE gaps cannot be repaired from DATA.
