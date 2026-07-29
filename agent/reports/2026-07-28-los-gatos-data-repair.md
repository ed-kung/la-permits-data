# Los Gatos (CA) data repair — 2026-07-28

Los Gatos was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` already has correct `FILE_DATE` (matches `DATA.date` / `search_data.Date` on all 1,999 rows) and correct `PERMIT_DATE` whenever both the field and a Permit Issuance Issued event are present. Main issues were `STATUS_ORIGINAL` lagging `DATA.status` (Finaled still Active/In Review; Issued still In Review; Plan Check still Active), Resolved stop-work cases left In Review, five Issued/Finaled rows missing `PERMIT_DATE` despite dated Issued events, and **every** row missing `FINAL_DATE` despite Closure Finaled/Resolved marks (and Approved `FINAL*` inspections) on nearly all Final records. Repair fixes 42 statuses, fills 5 permit dates and 1,382 final dates; residual gaps lack dated Issued / Closure Finaled / FINAL* inspection evidence in `DATA`.

## Jurisdiction selection

Walked `(JURISDICTION, STATE)` pairs in sample order and compared against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Los Gatos, CA** → `agent/scripts/ca/data_repair_ca_los_gatos.py` (n=1,999).

## DATA schema

All rows share Accela portal top-level keys (`address`, `date`, `status`, `tasks`, `inspections`, `search_data`, `fees_details`, …). Canonical status/dates:

| Source | Field |
| --- | --- |
| `DATA.status` / `search_data.Status` | STATUS_NORMALIZED |
| `DATA.date` / `search_data.Date` | FILE_DATE |
| Permit Issuance → Marked as Issued / Re-issued | PERMIT_DATE |
| Closure → Marked as Finaled / Resolved; else Approved inspection title containing `FINAL` | FINAL_DATE |

Content variants recorded in `INFERRED_SCHEMA`:

| Schema | n | Description |
| --- | ---: | --- |
| `portal_issued_finaled` | 1,347 | Issued + Closure Finaled/Resolved present |
| `portal_application_only` | 310 | Application / date only |
| `portal_issued` | 280 | Issued present, no Closure Finaled date |
| `portal_empty_tasks` | 43 | Empty / undated task shells |
| `portal_finaled_only` | 19 | Closure Finaled/Resolved, no Issued |

## Field assessment

### STATUS_NORMALIZED

- Missing on 2 / 1,999: blank `status` / `search_data.Status` (NPS commercial shells) → not fillable.
- Base map from `DATA.status` is already correct for most rows: Finaled/Complete→Final, Issued/issuedonline→Active, Expired/Void/Withdrawn/Canceled/Plan Check Expired→Inactive, Pre-Application Accepted/Plan Check/Processing/…→In Review.
- **Issues:** 15+ rows where `STATUS_ORIGINAL` lagged `DATA.status` (6 Active while DATA is Finaled; 4 In Review while Issued; 3 In Review while Finaled; 1 Active Plan Check; 1 Active Pending Corrections). Separately, 25 Resolved stop-work/violation rows were left In Review though Resolved means closed. One Active Issued row already had Closure Finaled while `DATA.status` still said Issued → promoted to Final.
- **Repair:** map from `DATA.status`; promote non-inactive rows with Closure Finaled/Resolved to Final; promote In Review with dated Issued to Active → **0 FILLED**, **42 FIXED**. Missing after: 2.

Status transitions: In Review→Final 28; Active→Final 7; In Review→Active 6; Active→In Review 1.

### FILE_DATE

- Missing on 0 / 1,999. Every value matches `DATA.date` (and `search_data.Date` when present).
- Application Acceptance Complete is occasionally 1–20 days earlier than `DATA.date`; the agency’s canonical opened date is the top-level `date` field already used for `FILE_DATE`, so those are not treated as errors.
- **Repair:** no changes (0 FILLED / 0 FIXED). Coverage 100%.

### PERMIT_DATE

- Missing on 377 / 1,999 (18.9%). When present, every value matches earliest Permit Issuance Issued/Re-issued (0 incorrect).
- Among Active/Final before repair: Active 134/135 present; Final 1,367/1,377 present. Recoverable: status-lagged Issued/Finaled rows that already had Issued events but null `PERMIT_DATE` (M24-124, M24-114, M24-137, M24-125, E24-140).
- **Repair:** **5 FILLED**, **0 FIXED**. Missing after: 372.
- Post-repair Active PERMIT coverage: 133/133 (100%); Final: 1,378/1,412 (97.6%). Remaining Final gaps are Resolved stop-work shells without Permit Issuance, and Finaled shells whose Issuance events are TBD/empty.

### FINAL_DATE

- Missing on 1,999 / 1,999 (100%). No pre-populated values to validate.
- Closure Finaled (and Resolved) marks carry dated finaling events for the large majority of Finaled/Resolved rows; Approved inspections with `FINAL` in the title fill additional Finaled rows whose Closure is Expired Permit / TBD.
- **Repair:** **1,382 FILLED**, **0 FIXED**. Missing after: 617 (almost all non-Final; 30 Final remain unfilled).
- Post-repair Final FINAL coverage: 1,382/1,412 (97.9%). Remaining 30 Final gaps are Resolved VIOs without Closure dates, Finaled rows with only Expired Permit/TBD Closure and no dated Approved `FINAL*` inspection, plus one Complete building-violation shell.

## Repair performance

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 42 | 2 | 2 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 5 | 0 | 377 | 372 |
| FINAL_DATE | 1,382 | 0 | 1,999 | 617 |

Status distribution after repair: Final 1,412 · In Review 263 · Inactive 189 · Active 133 · missing 2.

Post-repair completeness by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 133 | 100% | 100% | 0% |
| Final | 1,412 | 100% | 97.6% | 97.9% |
| In Review | 263 | 100% | 0% | 0% |
| Inactive | 189 | 100% | 61.4% | 0% |

Overall FILE_DATE coverage: 1,999 / 1,999 (100%). Active+Final PERMIT_DATE: 1,511 / 1,545 (97.8%).

Chronology: 2 `PERMIT < FILE` cases remain; both mirror Issued-before-opened stamps already present in Accela tasks (not introduced by repair). 0 `FINAL < PERMIT`.

## Artifacts

- Repair script: `agent/scripts/ca/data_repair_ca_los_gatos.py`
- Repaired sample: `$AGENT_DATA_PATH/repaired/permits_ca_los_gatos_repaired.parquet`
