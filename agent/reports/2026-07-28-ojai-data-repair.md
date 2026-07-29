# Ojai (CA) data repair

**Summary:** Ojai was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access DATA is present on all 2,000 sample rows. The main defects are `Meter Released` (and one `Issued`) shells left short of Final despite Final Inspection Complete, plus `FILE_DATE` lagging the earlier Application Accepted stamp on 139 rows. Repair promotes 81 statuses to Final and corrects 139 file dates; date fills are unnecessary because completion/issuance stamps were already copied when present. Script: `agent/scripts/ca/data_repair_ca_ojai.py`.

## Jurisdiction selection

First `(JURISDICTION, STATE)` in alphabetical order without `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Ojai, CA** (remaining gaps at selection time: Santee, Scotts Valley, Seaside, Soledad, Williams).

## DATA schema

| Schema | N | Notes |
| --- | ---: | --- |
| `portal_issued_finaled` | 1,121 | Permit Issuance Issued + Final Inspection Complete / Final CO |
| `portal_issued` | 712 | Issued present, no final-completion date |
| `portal_application_only` | 167 | Application / top-level date only (no Issued) |

Canonical sources: `DATA.status` / `search_data.Status`; earliest of `DATA.date` / `search_data.Date` / Application Acceptance|Submittal Accepted*|Submitted*; Permit Issuance Issued; Inspection Final Inspection Complete (fallback Certificate of Occupancy Final CO Issued). `inspections[]` is empty on every sample row.

## Findings by field

### STATUS_NORMALIZED

Before: Final 1,212, Active 530, In Review 232, Inactive 26, null 0.

Portal labels map cleanly for Finaled → Final, Issued → Active, CofO Issued → Final, Expired → Inactive, and Plan Review / Submitted / Ready to Issue / Revisions Required → In Review. Two mapping failures:

- **Meter Released (80)** left **In Review** even though every row has Permit Issuance Issued + Final Inspection Complete + Meter Released (and already carries `FINAL_DATE`). `STATUS_ORIGINAL=meter released` was never treated as post-issuance completion.
- **Issued with Final Inspection Complete (1)** left **Active** (portal lag); `FINAL_DATE` already present.

Repair: **0 FILLED, 81 FIXED**; missing after: **0**.

After: Final 1,293, Active 529, In Review 152, Inactive 26.

Transitions: In Review→Final 80 (`meter released`); Active→Final 1 (`issued` with Final Inspection Complete).

One Issued shell (OJ 24-346) has empty Permit Issuance events and open Zoning/Utilities review; portal status Issued is trusted → stays Active with missing `PERMIT_DATE`.

### FILE_DATE

Before: **0 missing**. Every row matches `DATA.date` / `search_data.Date` at calendar-day resolution.

139 rows have an earlier Application Acceptance/Submittal Accepted* stamp than the portal `date` field (median lag 2 days; max 351 on a reopened/revision shell). `FILE_DATE` is pulled back to that earlier application date.

Repair: **0 FILLED, 139 FIXED**. Coverage: **100%**.

### PERMIT_DATE

Before: **167 missing**. Present values match Permit Issuance Issued when that event exists (1,833 matches). Gaps are exclusively pre-issuance / expired shells (Plan Review 52, Submitted 41, Ready to Issue 37, Revisions Required 22, Expired 14) plus the one Issued shell without an Issued event.

After status repair, Active coverage is **528 / 529 (99.8%)**; Final **1,293 / 1,293 (100%)**. Spurious PERMIT_DATE on In Review: **0**.

Repair: **0 FILLED, 0 FIXED**. Remaining Active gap: OJ 24-346 (no Issued task event).

### FINAL_DATE

Before: **879 missing**. Where present, FINAL_DATE always matches Inspection Final Inspection Complete (or Final CO on the same day for CofO Issued). Meter Released / the lagging Issued shell already had correct completion dates under the wrong status.

Repair promotes those shells to Final (keeping dates) and does not invent completion dates for Finaled/CofO rows whose Inspection events are TBD.

Repair: **0 FILLED, 0 FIXED**. Final coverage after: **1,121 / 1,293 (86.7%)**. Non-Final rows with FINAL_DATE after repair: **0**.

Unfilled Final: 171 Finaled (Inspection TBD / Note / Approved only — Approved intermediate inspections not treated as final) + 1 CofO Issued (Inspection TBD, no Final CO Issued event).

## Repair script

`agent/scripts/ca/data_repair_ca_ojai.py` — `data_repair(df)` overwrites incorrect/missing fields, adds `{FIELD}_FLAG` (`FILLED` / `FIXED`) and `INFERRED_SCHEMA`.

Artifact: `$AGENT_DATA_PATH/repaired/permits_ca_ojai_repaired.parquet`.

### Performance (n=2,000)

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 0 | 81 | 0 | 0 |
| FILE_DATE | 0 | 139 | 0 | 0 |
| PERMIT_DATE | 0 | 0 | 167 | 167 |
| FINAL_DATE | 0 | 0 | 879 | 879 |

### Coverage after repair

| Check | Result |
| --- | --- |
| FILE_DATE present | 2,000 / 2,000 (100%) |
| PERMIT_DATE on Active | 528 / 529 (99.8%) |
| PERMIT_DATE on Final | 1,293 / 1,293 (100%) |
| FINAL_DATE on Final | 1,121 / 1,293 (86.7%) |
| FINAL_DATE on non-Final | 0 |

Ideal-coverage gaps that cannot be closed from DATA: 1 Active Issued shell without a dated Issued mark; 172 Final shells without Final Inspection Complete or Final CO Issued. Two chronology inversions remain in source workflow dates (Issued before Application Acceptance; Final Inspection Complete before Issued) and are left as-is.
