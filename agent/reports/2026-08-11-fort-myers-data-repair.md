# Fort Myers (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Fort Myers was first. DATA is mostly Tyler EnerGov (1,901 rows) plus a city storefront / utility-billing portal (100 rows). STATUS_NORMALIZED was null on 26 EnerGov rows whose CaseStatus values were unmapped upstream (including trailing-space variants); all were filled. FILE_DATE was already complete on EnerGov; 4 city-portal rows used dateCreated instead of dateSubmitted and were fixed. PERMIT_DATE already matched IssueDate whenever present (0 changes). FINAL_DATE gained 53 fills (6 from Passed final inspections, 47 from portal lastUpdatedDate) and 4 clears of non-Final void/close stamps, leaving FINAL_DATE on 98.8% of Final rows.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Fort Myers, FL** (2,001 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_fort_myers.py` (`data_repair`)

## DATA schema

| INFERRED_SCHEMA prefix | n | Notes |
| --- | ---: | --- |
| `energov` | 1,844 | entity/details/contacts/fees/processing_status |
| `energov_full` | 57 | + reviews/holds/attachments/more_info |
| `city_portal` | 100 | main/extra/location (utility & code workflows) |

EnerGov content suffixes (`_issued_finaled`, `_issued`, `_finaled`, `_applied`) reflect ApplyDate / IssueDate / FinalDate presence. City-portal suffixes (`_complete`, `_active`, `_draft`, `_stopped`) follow `main.status` codes 2 / 1 / 0 / -1.

Canonical mappings:

| Field | EnerGov source | City-portal source |
| --- | --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` | `main.status` |
| FILE_DATE | `ApplyDate` | `dateSubmitted` else `dateCreated` |
| PERMIT_DATE | `IssueDate` | *(none reliable)* |
| FINAL_DATE | `FinalDate` / `FinalizeDate`, else Passed final inspection | `lastUpdatedDate` when complete |

Inspection pass labels in this city are `Passed` / `Pass- Report to FPL` (not EnerGov `Approved`).

## Field assessments

### STATUS_NORMALIZED

26 missing (all EnerGov); remaining rows already matched CaseStatus / portal status codes. **26 FILLED, 0 FIXED:**

| CaseStatus → STATUS_NORMALIZED | n |
| --- | ---: |
| Ready to Issue with Notes → In Review | 10 |
| Pending Plan Review Fee → In Review | 6 |
| Approved Master → Final | 5 |
| Expired-Application → Inactive | 4 |
| Pending Final Fees → Active | 1 |

Cause: upstream normalization left these CaseStatus values unmapped (two statuses also carry trailing spaces in DATA). After repair: Final 1,622; Inactive 163; In Review 130; Active 86; none missing.

### FILE_DATE

Ideal: populated for all records.

- EnerGov: **already correct** — every FILE_DATE matches ApplyDate.
- City portal: FILE_DATE had been set from `dateCreated`; **4 FIXED** to `dateSubmitted` when that differed (same-day or next-day submittal). Remaining portal rows already matched the preferred source. 0 missing before/after.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When IssueDate present, PERMIT_DATE already equaled it (no incorrect values).
- **0 FILLED / 0 FIXED.**
- Remaining gap: **359 Active/Final** still missing PERMIT_DATE — 307 EnerGov Final (and 11 city-portal Active + 47 city-portal Final) with null IssueDate / no issuance field. Not inventable from DATA.

Coverage after repair: Active 75/86 (87.2%); Final 1,263/1,622 (77.9%); In Review 0/130; Inactive 57/163.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: 26 Final EnerGov rows missing FINAL_DATE; 4 non-Final rows had FINAL_DATE (Pending / In Review / Void / Cancelled) equal to FinalDate void/close stamps; all 47 city-portal Final rows missing FINAL_DATE.
- **53 FILLED** (6 from Passed final-ish inspections when FinalDate null; 47 from portal `lastUpdatedDate` on complete).
- **4 FIXED** (cleared non-Final FINAL_DATE).
- Remaining: **20 Final** rows (19 Closed, 1 Finaled) with neither FinalDate nor a Passed final inspection.

Coverage after repair: Final 1,602/1,622 (98.8%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 26 | 0 | 26 → 0 |
| FILE_DATE | 0 | 4 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 606 → 606 |
| FINAL_DATE | 53 | 4 | 448 → 399 |

Post-repair consistency checks (status vs CaseStatus / portal map; FILE vs ApplyDate or dateSubmitted; PERMIT vs IssueDate / absent on In Review; FINAL only on Final and equal to FinalDate, inspection date, or portal lastUpdatedDate): **0 violations**.

## Artifacts

- Repair function: `agent/scripts/fl/data_repair_fl_fort_myers.py`
