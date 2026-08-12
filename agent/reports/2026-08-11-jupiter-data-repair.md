# Jupiter (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Jupiter was first. Its DATA is a uniform Tyler EnerGov payload (`entity` / `details` / `fees` / `contacts` / `processing_status`). The main defect is 76 unmapped `CaseStatus` values left as null STATUS_NORMALIZED, plus 4 stale Active rows whose CaseStatus is already `99 - Closed - JCDS`. Repair fills all statuses from CaseStatus, promotes the lagged Closed-JCDS rows to Final (FINAL_DATE from FinalDate), fills 2 missing Issued PERMIT_DATEs, and fills the one Closed-HTE Final missing FINAL_DATE from a Passed Plumbing Final inspection. FILE_DATE was already complete and correct. After repair: Active and Final have 100% FILE_DATE; Active 100% / Final 97.4% PERMIT_DATE; Final 100% FINAL_DATE.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Jupiter, FL** (1,998 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_jupiter.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/jupiter_repaired_sample.parquet`

## DATA schema

All records are EnerGov-shaped. Most use the basic key set; 22 recent rows also include `reviews` / `holds` / `attachments` / `more_info` (`energov_rich_*`).

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,791 | IssueDate + FinalDate |
| `energov_finaled` | 79 | FinalDate only (legacy closed, no IssueDate) |
| `energov_issued` | 65 | IssueDate only |
| `energov_applied` | 41 | ApplyDate only |
| `energov_rich_issued` | 11 | rich portal + IssueDate |
| `energov_rich_applied` | 10 | rich portal + ApplyDate |
| `energov_rich_issued_finaled` | 1 | rich portal + both dates |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` / `details.PermitStatus` |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) |
| FINAL_DATE | `FinalDate` / `FinalizeDate`; else Passed final-ish `processing_status` inspection on/after IssueDate |

## Field assessments

### STATUS_NORMALIZED

76 missing; 4 incorrect Active labels on already-closed JCDS rows.

Upstream mapped only the common closed / issued / cancelled codes. Everything else (`30 - In Review`, `76 - Permit - CO/CC`, `90 - Permit - Expired`, `NOC Required`, fees-due / documents / received variants, etc.) stayed null. Four rows kept STATUS_ORIGINAL `70 - issued` → Active while CaseStatus had advanced to `99 - Closed - JCDS` (and FinalDate was present but FINAL_DATE empty).

**76 FILLED** (largest):

| DATA.CaseStatus | → | n |
| --- | --- | ---: |
| 76 - Permit - CO/CC | Final | 10 |
| 90 - Permit - Expired | Inactive | 10 |
| 30 - In Review | In Review | 14 |
| NOC Required | Active | 8 |
| 32 / 34 In Review corrections | In Review | 8 |
| 16 - Pending Documents | In Review | 5 |
| 52 / 12 Fees Due* | In Review | 5 |
| 10 - Received JCDS | In Review | 4 |
| 97 - Closed - Duplicate | Inactive | 3 |
| 70 - Issued | Active | 3 |
| 60 - Application - Expired | Inactive | 2 |
| 18 - Pre-Review Verification | In Review | 2 |
| 54 Sub-Permit On Hold / 39 Revisions | In Review / Active | 2 |

**4 FIXED:** Active → Final on `99 - Closed - JCDS` (portal status lag vs STATUS_ORIGINAL).

Override rules: FinalDate promotes Active/In Review to Final only when it does not predate IssueDate (avoids one Issued row with a stale earlier FinalDate). `39 - In Review - Revisions` with IssueDate → Active.

After repair: Final 1,836; Inactive 66; Active 57; In Review 39; null 0.

### FILE_DATE

Ideal: populated for all records. **Already correct** — 0 missing; every FILE_DATE matches `entity.ApplyDate` at day resolution (6 entity/details ApplyDate pairs differ by UTC vs local midnight; entity is canonical). No FILLED/FIXED.

### PERMIT_DATE

Ideal: populated for Active and Final.

| Action | n |
| --- | ---: |
| FILLED from IssueDate | 2 |

The 2 fills are Issued rows whose STATUS_ORIGINAL lagged (`52 - fees due` / `30 - in review`) so PERMIT_DATE was never set; CaseStatus/IssueDate are present.

Remaining gap: **48 Final** still missing PERMIT_DATE — Closed-HTE/JCDS rows with blank IssueDate in DATA. Not inventable. Active coverage after repair: **57/57 (100%)**; Final **1,788/1,836 (97.4%)**.

### FINAL_DATE

Ideal: populated for Final.

| Action | n |
| --- | ---: |
| FILLED (4 Closed-JCDS FinalDate + 1 Plumbing Final insp.) | 5 |
| FIXED cleared (Cancelled / Expired / Duplicate closure stamps on non-Final) | 36 |

Cause of clears: Inactive Cancelled (and similar) rows stored agency `FinalDate` as a closure stamp; those are not permit finals. One Closed-HTE Final (`16-001880-PLUMC`) had blank FinalDate but a Passed `Plumbing Final` inspection → FILLED.

After repair: Final **1,836/1,836 (100%)**; no FINAL_DATE on non-Final; chronology clean (0 PERMIT&lt;FILE, 0 FINAL&lt;PERMIT).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 76 | 4 | 76 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 2 | 0 | 132 → 130 |
| FINAL_DATE | 5 | 36 | 131 → 162 |

FINAL_DATE missing count rises because 36 non-Final closure stamps were cleared (FIXED), which is intentional.

Coverage after repair:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 57 | 100% | 100% | 0% |
| Final | 1,836 | 100% | 97.4% | 100% |
| In Review | 39 | 100% | 12.8% | 0% |
| Inactive | 66 | 100% | 27.3% | 0% |
