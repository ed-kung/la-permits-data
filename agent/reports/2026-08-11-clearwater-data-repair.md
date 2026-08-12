# Clearwater (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Clearwater was first. Its DATA is a uniform Accela Citizen Access payload. STATUS_NORMALIZED had 38 nulls and 242 mislabels (mainly Retired→In Review and Complied→In Review). FILE_DATE was already complete and correct. PERMIT_DATE and FINAL_DATE were entirely missing upstream; the repair filled 913 permit dates and 1,315 final dates from `PERMIT DATES`, workflow tasks, and inspections, leaving FINAL_DATE on 82.3% of Final rows and PERMIT_DATE on 89.4% of Active rows.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Clearwater, FL** (2,001 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_clearwater.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/clearwater_repaired_sample.parquet`

## DATA schema

All records are Accela-shaped (`status`, `date`, `tasks`, `search_data`, `more_details`). Most also include `inspections`, `fees_details`, `contacts`, and `related_records`. A few sparse rows omit those blocks.

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `accela_full_issued_finaled` | 829 | inspections + issued + final dates |
| `accela_basic_applied` | 500 | dated tasks; no recoverable issue/final |
| `accela_basic_finaled` | 481 | final date only |
| `accela_full_issued` | 83 | issued, no final |
| `accela_full_applied` | 58 | inspections present; no issue/final |
| `accela_full_finaled` | 49 | final only |
| `accela_basic_issued` | 1 | issued only |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `DATA.status` (fallback `search_data.Status`) |
| FILE_DATE | `DATA.date` / `search_data.Date` |
| PERMIT_DATE | `more_details` → `PERMIT DATES.Issued`; else Permit Verification `Issue`; else Enforcement / Digital Plan Review `Permit Issued` |
| FINAL_DATE | `PERMIT DATES.Finaled`; else Active Permit completion/CO/CC marks; else Passed final-ish inspections; else enforcement compliance / Abatement `Repaired`; else (Closed-family) latest Pass/DONE inspection |

## Field assessments

### STATUS_NORMALIZED

38 missing; several systematic mislabels vs `DATA.status`.

**38 FILLED** (unmapped originals): License Holder Self Certify→Final (13), Revisions Needed→In Review/Active (12), Building Repaired→Final (4), No Access - Owner Refused→In Review (3), Active (2), plus single-row Compliant / Owner Demo / Economic Development / Review Approved.

**242 FIXED** (largest):

| Before → After | DATA.status | n |
| --- | --- | ---: |
| In Review → Inactive | Retired | 195 |
| In Review → Final | Complied | 41 |
| Active → Final | Completed | 2 |
| In Review / Inactive → Active | Active / Hold / Stop Work Order | 4 |

Cause: upstream normalization treated Accela `Retired` and enforcement `Complied` as review states, left niche statuses null, and lagged `DATA.status` on a few Active rows (STATUS_ORIGINAL still `expired` / `additional info required` / `revisions needed`). Hold and Revisions Needed after Permit Verification `Issue` are upgraded to Active.

After repair: Final 1,598; Inactive 280; Active 66; In Review 57; null 0.

### FILE_DATE

Ideal: populated for all records. **Already correct** — 0 missing; every FILE_DATE matches `DATA.date` at day resolution. No FILLED/FIXED.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Upstream: **100% missing** (never ingested).
- **913 FILLED** from `PERMIT DATES.Issued` and/or Permit Verification `Issue` (task Issue covers ~399 rows beyond the 507 with `PERMIT DATES.Issued`).
- Remaining gap: **757 Active/Final** still missing PERMIT_DATE — mostly Completed / Closed / No Violation / Complied rows with no Issued field and no Issue task (common on legacy and enforcement records). Not inventable from DATA.

Coverage after repair: Active 59/66 (89.4%); Final 841/1,598 (52.6%); In Review 0/57; Inactive 13/280.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream: **100% missing**.
- **1,315 FILLED** (361 from `PERMIT DATES.Finaled`, plus Active Permit `Completed`/CO/CC marks, Passed final inspections, and enforcement compliance / Abatement `Repaired` / Pass-DONE fallbacks for Closed-family rows).
- Remaining: **283 Final** rows with neither Finaled nor a usable completion event/inspection (many Completed shells and some Complied / No Violation).
- Non-Final FINAL_DATE stays empty (0 spurious values to clear). No PERMIT_DATE > FINAL_DATE inversions.

Coverage after repair: Final 1,315/1,598 (82.3%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 38 | 242 | 38 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 913 | 0 | 2,001 → 1,088 |
| FINAL_DATE | 1,315 | 0 | 2,001 → 686 |
