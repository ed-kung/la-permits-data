# Whittier CA data repair

**Summary:** Whittier’s 2,000 sample records are Accela Citizen Access payloads (`tasks` / `status` / `date` / `inspections` / `fees_details`). All rows share one schema (`tasks_full`). Main defects: 11 unmapped pre-issuance statuses leaving `STATUS_NORMALIZED` null; 5 rows with `Inspections / Finaled` while `DATA.status` is still Issued/Received/Pending; `FINAL_DATE` storing the first Finaled when a later Finaled exists; missing `FINAL_DATE` on Closed enforcement cases; and missing `PERMIT_DATE` on Approved discretionary records that never hit Permit Issuance. Script: `agent/scripts/data_repair_ca_whittier.py`.

## Data & schema

| Item | Value |
| --- | --- |
| Source | `MY_DATA_PATH/processed_data/permits_la_sample.parquet` |
| Filter | `JURISDICTION == "Whittier"`, `STATE == "CA"` |
| N | 2,000 |
| First jurisdiction without an existing `data_repair_{state}_{city}.py` | Whittier, CA (La Cañada Flintridge already covered by `data_repair_ca_la_canada_flintridge.py`) |

| INFERRED_SCHEMA | n |
| --- | --- |
| `tasks_full` | 2,000 |

Canonical fields:

| Target field | DATA source |
| --- | --- |
| `STATUS_NORMALIZED` | `DATA.status`, overridden to Final when `Inspections / Finaled` exists |
| `FILE_DATE` | `DATA.date` (fallback `search_data['Date']`) |
| `PERMIT_DATE` | earliest `Permit Issuance / Issued`; for `Approved`, approval workflow events |
| `FINAL_DATE` | latest `Inspections / Finaled`; else `Closed / Close`; else Investigation Abated / No Violation / Duplicate |

Status map: Finaled / Permanent CofO / Temporary CofO / Closed → Final; Issued / Approved / Reinstated → Active; Expired / Cancelled / Void / Revoked / Violation → Inactive; Pending* / In Review / Ready to Issue / Open / Received / Incomplete Submittal / Corrections* / Revisions Required / Report / Verification In Progress / Fire Flow* → In Review.

## Field assessment

### STATUS_NORMALIZED — 11 missing; 5 incorrect

Upstream mapping covered most Accela statuses. Gaps and errors:

| Issue | n | Repair |
| --- | --- | --- |
| Unmapped `Pending Documents` / `Fire Flow In Progress` / `Pending Fire Flow` / `Verification In Progress` → null | 11 | FILLED → In Review |
| `Inspections / Finaled` present but `DATA.status` still Issued (2), Received (2), or Pending (1) | 5 | FIXED → Final |

After repair: 0 missing. Distribution: Final 929, Active 624, In Review 242, Inactive 205.

### FILE_DATE — complete and correct

- Ideal: application / submittal date for all records.
- 2,000 / 2,000 match the calendar day of `DATA.date` (0 mismatches, 0 missing).
- No FILLED / FIXED.

### PERMIT_DATE — correct when present; Approved gaps filled

- Ideal: populated for Active and Final.
- Where both `PERMIT_DATE` and `Permit Issuance / Issued` exist, day matches for all 1,363 Active/Final rows with an Issued event (0 mismatches).
- FILLED 82: all `DATA.status == Approved` (Development Review Counter / Revision / etc.) using Review Consolidation / department Review / Application Submittal Approved* / Plans Distribution OTC.
- Missing before → after: 622 → 540.
- After repair: Active 623 / 624 (99.8%); Final 822 / 929 (88.5%).
- Remaining Active gap (1): `Issued` Residential Solar with no Issued event in tasks (Application Submittal still TBD).
- Remaining Final gaps (107): almost all Closed Enforcement Case (84) / Special Inspector Registration (13) / New Address (2) / Investigation (4) with no Permit Issuance — not building-permit issuances. A few Finaled rows lack Issued events in workflow.

### FINAL_DATE — Final rows mostly recoverable; first-vs-latest Finaled fixed

- Ideal: populated for Final.
- Upstream often stored the **first** `Inspections / Finaled` when a later Finaled exists (10 rows).
- Repair uses **latest** Finaled; else `Closed / Close`; else Investigation close-out (Abated / No Violation / Duplicate).
- FILLED 86: Closed enforcement / payment-close rows (84 Investigation + 2 Closed/Close).
- FIXED 10: all first→latest Finaled corrections. The 5 stale-status rows upgraded to Final already carried a correct Finaled date, so no clear was needed.
- After repair: Final 913 / 929 (98.3%); Active / In Review / Inactive have none.
- 16 Final rows remain without `FINAL_DATE`: 13 Special Inspector Registration (empty tasks), 2 Finaled with Inspections still TBD / empty workflow, 1 Temporary CofO (Temporary CofO event is not treated as completion).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| `STATUS_NORMALIZED` | 11 | 5 | 11 → 0 |
| `FILE_DATE` | 0 | 0 | 0 → 0 |
| `PERMIT_DATE` | 82 | 0 | 622 → 540 |
| `FINAL_DATE` | 86 | 10 | 1,173 → 1,087 |

Coverage vs ideals (after repair):

| Ideal | Result |
| --- | --- |
| `FILE_DATE` for all | 2,000 / 2,000 (100%) |
| `PERMIT_DATE` for Active | 623 / 624 (99.8%) |
| `PERMIT_DATE` for Final | 822 / 929 (88.5%) |
| `FINAL_DATE` for Final | 913 / 929 (98.3%) |

## Artifacts

- Script: `agent/scripts/data_repair_ca_whittier.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/whittier_repaired_sample.parquet`
