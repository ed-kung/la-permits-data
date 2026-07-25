# San Diego CA data repair

**Summary:** San Diego’s 1,996 sample records split roughly evenly across two DATA schemas — Accela `tasks` (1,045) and Project Status XML `approval_project` (951). The main defects are (1) `STATUS_NORMALIZED` lagging behind live `DATA.status` / `Approval.Status` (44 FIXED), (2) missing `FILE_DATE` on `approval_project` rows with no `ApplicationDate` (183 FILLED from invoice/review-cycle proxies), (3) missing `PERMIT_DATE` on Accela Issued/Approved rows whose issuance is recorded on Fees/Review tasks (151 FILLED + 2 FIXED), and (4) missing `FINAL_DATE` on Closed/Completed Final rows (80 FILLED). Script: `agent/scripts/data_repair_ca_san_diego.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` |
| Filter | `JURISDICTION == "San Diego"`, `STATE == "CA"` |
| N | 1,996 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | San Diego, CA (after Los Angeles) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `tasks` | 1,045 |
| `approval_project` | 951 |

Canonical fields:

| Target field | `tasks` source | `approval_project` source |
| --- | --- | --- |
| `STATUS_NORMALIZED` | `DATA.status` | `approval.Approval.Status` |
| `FILE_DATE` | `DATA.date` | `project.ApplicationDate` → earliest `InvoiceIssueDate` → earliest ReviewCycle date |
| `PERMIT_DATE` | `Issuance`/`Permit Issuance`/`Fees`/`Review` → `Issued` (fallback Issuance `Approved`) | `approval.Approval.IssueDate` |
| `FINAL_DATE` | `Inspections`/`Finaled` → `Closed`/`Closeout` close → `Job Sign Off`/`Completed` | `approval.Approval.CompleteCancelDate` |

`DATA.status` / `Approval.Status` are authoritative over `STATUS_ORIGINAL` (tasks: 16 casefold mismatches; approval_project: 30), which is often stale.

### Status maps

**tasks:** Closed → Final; Issued / Approved / Inspecting / Inspection Followup → Active; Cancelled* / Withdrawn / Application Expired / Failed Scout Validation → Inactive; Opened / Created / In Review / Review Phase Complete / Approved Upon Final Payment / Deemed Complete / … → In Review.

**approval_project:** Completed → Final; Issued → Active; Created / Pending Invoice Payment → In Review; Cancelled-* → Inactive.

## Field assessment

### STATUS_NORMALIZED — 25 missing; 44 incorrect

| Issue | n | Repair |
| --- | --- | --- |
| `approval_project`: Completed → Active/In Review (should be Final) | 14 | FIXED |
| `approval_project`: Issued → In Review (should be Active) | 9 | FIXED |
| `approval_project`: Cancelled-* → Active/In Review (should be Inactive) | 7 | FIXED |
| `tasks`: Closed → Active (should be Final; stale STATUS_ORIGINAL=issued) | 5 | FIXED |
| `tasks`: Issued → In Review (should be Active) | 6 | FIXED |
| `tasks`: Cancelled → Active; Application Expired → In Review; Deemed Complete → Final | 3 | FIXED |
| Dependent Approvals (`DATA.status` null, no STATUS_ORIGINAL) | 25 | unfillable |

After repair, every mapped row matches the tables above (0 mismatches). Distribution shifts slightly toward Final (768 → 786) and Inactive (169 → 178). The 25 Dependent Approvals remain NaN — no status signal in DATA.

### FILE_DATE — tasks complete; approval_project gaps mostly fillable

- Ideal: application / submittal date for all records.
- **tasks:** 1,045 / 1,045 already match `DATA.date` (0 missing, 0 FIXED).
- **approval_project:** 208 missing `ApplicationDate` and `FILE_DATE`. Of those, 183 fillable from earliest `InvoiceIssueDate` (preferred) or ReviewCycle dates. Invoice dates track ApplicationDate within ±1 day for ~69% of rows that have both.
- Missing before → after: 208 → 25 (remaining have no ApplicationDate, invoices, or review cycles).

### PERMIT_DATE — Active/Final largely recoverable

- Ideal: populated for Active and Final.
- **tasks:** Upstream correctly used `Issuance`/`Permit Issuance`/`Issued` when present (499 day-matches). Gaps: 166 Active/Final missing — mostly OTC-style permits that only have `Fees`/`Review`/`Issued` (111) or Issuance/`Approved` without a separate Issued step (35). Two Closed rows stored Invoice Paid instead of Issued → FIXED.
- **approval_project:** Active/Final already had `IssueDate` as PERMIT_DATE. 9 In Review rows gained IssueDate fill only after status FIXED to Active.
- Missing before → after: 632 → 472.
- After repair: Active 651 / 652 (99.8%); Final 767 / 786 (97.6%).
- Remaining gaps: 1 Issued Combination Building Permit with only Inspections/TBD; 19 Closed Final project-type records (PTS / PV / Fire) with no issuance event in tasks.

### FINAL_DATE — Final rows mostly recoverable; Active cleared

- Ideal: populated for Final.
- Prefer `Inspections`/`Finaled` (matches “finaled” semantics and existing correct values); else Closed/Closeout close events.
- FILLED 80 (66 tasks + 14 approval_project Completed→Final with CompleteCancelDate).
- FIXED 9: all clearing spurious FINAL_DATE on Active tasks rows (Issued / Inspection Followup).
- Four Final rows whose FINAL_DATE equals Inspections/Finaled but Closed is later were left unchanged (Inspections Finaled is the preferred source).
- After repair: Final 772 / 786 (98.2%); Active / In Review have none.
- 14 Final gaps remain (Project-PTS style Closed rows with empty/TBD task timelines).
- Inactive keeps CompleteCancelDate in FINAL_DATE for 93 cancelled approval_project rows (cancel date, not a true final — left as-is).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 0 | 44 | 25 → 25 |
| `FILE_DATE` | 183 | 0 | 208 → 25 |
| `PERMIT_DATE` | 160 | 2 | 632 → 472 |
| `FINAL_DATE` | 80 | 9 | 1,202 → 1,131 |

Flags by schema:

| Field | tasks FILLED/FIXED | approval_project FILLED/FIXED |
| --- | --- | --- |
| STATUS | 0 / 14 | 0 / 30 |
| FILE_DATE | 0 / 0 | 183 / 0 |
| PERMIT_DATE | 151 / 2 | 9 / 0 |
| FINAL_DATE | 66 / 9 | 14 / 0 |

## Artifacts

- Repair script: `agent/scripts/data_repair_ca_san_diego.py`
- Function: `data_repair(df)` → copy with repaired fields, `{FIELD}_FLAG` (`FILLED`/`FIXED`), and `INFERRED_SCHEMA`
