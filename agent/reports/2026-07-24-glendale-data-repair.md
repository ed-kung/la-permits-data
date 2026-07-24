# Glendale CA data repair

**Summary:** Glendale’s 2,001 sample records are Tyler EnerGov payloads (`entity` / `details` / `fees`, with an optional reviews bundle). `FILE_DATE` already matches `entity.ApplyDate` (UTC day) for every row. The main defects are (1) `STATUS_NORMALIZED` derived from stale `STATUS_ORIGINAL` that disagrees with `entity.CaseStatus` on 26 rows, plus 25 `Pending Expiration` rows that should be Active; (2) `FINAL_DATE` copied from `entity.FinalDate` on 287 non-Final cases where that field is a short-term end / expire proxy, not a sign-off; (3) a handful of missing `PERMIT_DATE` / `FINAL_DATE` values fillable after status remap. Repair fixes 46 statuses, fills 5 `PERMIT_DATE` and 11 `FINAL_DATE` values, corrects 1 mismatched Final date, and clears 287 spurious finals. Script: `agent/scripts/data_repair_ca_glendale.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Glendale"`, `STATE == "CA"` |
| N | 2,001 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Glendale, CA (after Alhambra … Gardena) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `entity_fees` | 1,916 |
| `entity_fees_reviews` | 85 |

Canonical fields under `entity` (details used as fallback):

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `entity.CaseStatus` (fallback `details.PermitStatus`) |
| `FILE_DATE` | `entity.ApplyDate` |
| `PERMIT_DATE` | `entity.IssueDate` |
| `FINAL_DATE` | `entity.FinalDate` (fallback `details.FinalizeDate`) |

`ExpireDate` is a validity window, not a completion date. On Issued / Expired short-term permits (film, street use, ROW), `FinalDate` often equals `IssueDate` or `ExpireDate` and is not a finaling date.

## Field assessment

### STATUS_NORMALIZED — 0 missing; 46 incorrect

Upstream mapped `STATUS_ORIGINAL` (lowercased portal label) → normalized status. That label disagrees with current `entity.CaseStatus` on 26 rows, so normalized status followed the stale label:

| CaseStatus | Was | Should be | n |
| --- | --- | --- | --- |
| Final | Active / Inactive / In Review | Final | 11 |
| Issued | In Review | Active | 4 |
| Expired | Active | Inactive | 4 |
| Void | In Review | Inactive | 1 |
| In Review | Active | In Review | 1 |
| Pending Expiration | Active | (see below) | 1 |

Additionally, all 26 `Pending Expiration` rows have `IssueDate` and `details.Issued=True` (permit already issued, nearing expiry). Upstream put 25 as In Review; repair maps them to Active (+25 FIXED). Combined with the CaseStatus remaps above → **46 FIXED**.

Status map used: Final/COO/Complete → Final; Issued/Permit Extended/Pending Expiration → Active; Expired/Permit Expired/Void/Withdrawn/Denied → Inactive; remaining pre-issuance labels (In Review, Fees Due/Paid, On Hold, Processing, Ready to Issue, Submitted*, Waiting on Applicant, PC Extended) → In Review.

### FILE_DATE — complete and correct

No missing values. All 2,001 rows match the UTC calendar day of `entity.ApplyDate`. No FILLED/FIXED.

### PERMIT_DATE — mostly correct; 5 fillable after status fix

| Status (pre-repair) | Missing | Notes |
| --- | --- | --- |
| Active | 2 | Both `IssueDate` null in DATA (Valet Parking; Fire Alarm) — unfillable |
| Final | 32 | `IssueDate` null, mostly Code Modification / Change of Address / legacy — unfillable |
| In Review | 114 | Expected for pre-issuance; 4 Issued-mislabeled rows become Active and get filled |
| Inactive | 106 | Optional |

Where both `PERMIT_DATE` and `IssueDate` exist, UTC day always matches (0 mismatches). Repair **FILLED 5** from `IssueDate` after status remaps (Issued→Active and similar). Remaining Active/Final gaps (~34) have no issuance date in DATA; `FILE_DATE` is not used as a proxy (same convention as Alhambra/Arcadia).

### FINAL_DATE — all Final rows populated; 287 spurious on non-Final

| Issue | n | Action |
| --- | --- | --- |
| Non-Final with `FINAL_DATE` (= `entity.FinalDate`) | 287 | Clear (FIXED). CaseStatus Issued×174, Expired×97, Fees Due×10, Submitted×2, Permit Expired×2, Withdrawn×2 |
| CaseStatus Final but status mislabeled; `FinalDate` present, `FINAL_DATE` already set | 11 | Status FIXED to Final; date already present |
| CaseStatus Final (mislabeled) with `FinalDate` but null `FINAL_DATE` | 11 | FILLED from `FinalDate` after status fix |
| COO Final row: `FINAL_DATE` 2024-06-25 vs `FinalDate` 2024-06-21T23:30:30Z | 1 | FIXED to `FinalDate` |

After repair, every Final record has `FINAL_DATE`; Active / In Review / Inactive have none.

## Repair performance (sample)

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 0 | 46 | 0 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 5 | 0 | 254 → 249 |
| `FINAL_DATE` | 11 | 288 | 570 → 846 |

Missing `FINAL_DATE` rises because 287 non-Final spurious values are cleared; among Final rows coverage is 1,155 / 1,155 (100%).

| STATUS_NORMALIZED | Before | After |
| --- | --- | --- |
| Final | 1,144 | 1,155 |
| Active | 323 | 342 |
| Inactive | 381 | 381 |
| In Review | 153 | 123 |

Post-repair date coverage by status:

| Status | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- |
| Active | 340 / 342 (99.4%) | 0 / 342 |
| Final | 1,123 / 1,155 (97.2%) | 1,155 / 1,155 (100%) |
| In Review | 15 / 123 (12.2%) | 0 / 123 |
| Inactive | 274 / 381 (71.9%) | 0 / 381 |

## Artifacts

- Repair script: `agent/scripts/data_repair_ca_glendale.py` (`data_repair`)
- No derived datasets written under `AGENT_DATA_PATH`
