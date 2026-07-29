# Lake Elsinore (CA) data repair

**Summary:** Lake Elsinore was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script (appearance index 222). All 2,000 sample rows carry Tyler EnerGov-style DATA JSON. Status repairs fix 50 rows (Approved→In Review, Issued+FinalDate→Final, review shells with IssueDate→Active, Test→Inactive). FILE_DATE is already complete and correct. PERMIT_DATE gains 1 fill; FINAL_DATE clears 18 junk stamps on non-Final rows. Remaining gap: 7 Final rows with null IssueDate. Script: `agent/scripts/ca/data_repair_ca_lake_elsinore.py`.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in `permits_ca_sample.parquet` appearance order without `agent/scripts/{state}/data_repair_{state}_{city}.py` (accent-normalized slug): **Lake Elsinore, CA** (index 222, after Aliso Viejo).

## DATA schema

| Schema | N | Notes |
| --- | ---: | --- |
| `entity_basic` | 1,374 | entity + details + contacts + processing_status |
| `entity_fees` | 431 | entity_basic + fees |
| `entity_fees_reviews` | 195 | entity_fees + reviews/holds/attachments/more_info |

Canonical fields: `entity.CaseStatus` / `details.PermitStatus` (uppercase labels), `ApplyDate` → FILE_DATE, `IssueDate` → PERMIT_DATE, `FinalDate` / `details.FinalizeDate` → FINAL_DATE. `ClosedDate` / `CompleteDate` are null on every sample row. `ExpireDate` is a validity window (one 2099 sentinel), not used as FINAL_DATE.

## Findings by field

### STATUS_NORMALIZED

Before: no missing values (Active 427, Final 507, In Review 361, Inactive 705).

Most CaseStatus labels already map correctly (EXPIRED/VOID/…→Inactive, FINAL/CLOSED→Final, ISSUED/EXTENSION→Active, SUBMITTED*/IN REVIEW/ON HOLD→In Review).

Incorrect mappings:

| Issue | N | Reason |
| --- | ---: | --- |
| `APPROVED` left Active | 35 | Upstream maps `approved`→Active; plan approval without issuance should be In Review. 3 of 35 have IssueDate and correctly stay Active via the issuance override; 32 FIXED to In Review. |
| `ISSUED` with FinalDate after IssueDate left Active | 11 | Completion stamp present; FIXED to Final. |
| Review-pipeline + IssueDate left In Review | 5 | SUBMITTED (1), SUBMITTED - ONLINE (2), ON HOLD (1), PLANNING APPROVED (1) → FIXED to Active. |
| `TEST` left In Review | 2 | FIXED to Inactive. |

Repair: **0 FILLED, 50 FIXED**; missing after: **0**.

After: Inactive 707, Final 518, Active 389, In Review 386.

### FILE_DATE

Before: **0 missing**. Matches `entity.ApplyDate` at calendar-day resolution on all 2,000 rows.

Repair: **0 FILLED, 0 FIXED**. Coverage **100%**.

Note: 142 rows have ApplyDate calendar-day after IssueDate in the agency payload; those inversions are preserved (not inventable from DATA).

### PERMIT_DATE

Before: **475 missing**. Matches IssueDate on all 1,525 populated rows that have an IssueDate.

Issues:

- 1 In Review / `SUBMITTED - ONLINE` row had IssueDate (`2025-01-07`) but null PERMIT_DATE → promoted to Active and PERMIT_DATE **FILLED**.
- Active rows missing PERMIT_DATE were almost entirely mislabeled `APPROVED` shells without IssueDate (corrected via status).
- 7 `FINAL` rows have null IssueDate (signs / certificate-of-occupancy style) → PERMIT_DATE cannot be filled.

Repair: **1 FILLED, 0 FIXED**. Missing after: **474**.

After repair: Active PERMIT_DATE coverage **100%**; Final **511 / 518 (98.6%)**.

### FINAL_DATE

Before: **1,464 missing**. When present, matches FinalDate/FinalizeDate exactly (536 rows).

Issues:

- 11 Active `ISSUED` rows already carried a correct FINAL_DATE and are promoted to Final (status FIXED; date left as-is).
- 14 Inactive `VOID` rows carried FinalDate as a case-closure stamp → FINAL_DATE **FIXED** (cleared).
- 4 `APPROVED` rows carried FinalDate without IssueDate → status to In Review; FINAL_DATE **FIXED** (cleared; not treated as completion without issuance).

Repair: **0 FILLED, 18 FIXED** (all clears). Final coverage after repair: **518 / 518 (100%)**. Non-Final FINAL_DATE: **0**.

One agency chronology inversion remains: Final row `FCON-2019-00175` has IssueDate after FinalDate in source; left unchanged.

## Repair script

`agent/scripts/ca/data_repair_ca_lake_elsinore.py` — `data_repair(df)` overwrites incorrect/missing fields from DATA, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Status logic (EnerGov convention, matching Simi Valley / Healdsburg):

1. Inactive labels sticky (including TEST / REFUND/CANCELLED).
2. Final/Closed label, or FinalDate strictly after IssueDate → Final.
3. IssueDate present → Active.
4. Else map CaseStatus/PermitStatus (Approved → In Review).

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 50 | 0 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 1 | 0 | 475 | 474 |
| FINAL_DATE | 0 | 18 | 1,464 | 1,482 |

### Coverage after repair

| Check | Result |
| --- | --- |
| FILE_DATE present | 2,000 / 2,000 (100%) |
| PERMIT_DATE on Active | 389 / 389 (100%) |
| PERMIT_DATE on Final | 511 / 518 (98.6%) |
| FINAL_DATE on Final | 518 / 518 (100%) |
| FINAL_DATE on non-Final | 0 |

Ideal-coverage gap that cannot be closed from DATA: **7 Final rows** missing PERMIT_DATE (null IssueDate).

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_lake_elsinore.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_lake_elsinore_repaired.parquet`
