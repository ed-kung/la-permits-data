# Martinez (CA) data repair

Martinez was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. Accela Citizen Access JSON under `DATA` supports filling all 421 blank statuses from workflow/inspection evidence, correcting 2 mis-mapped labels (`Fee Estimate`, `Reactivated`), and filling 212 missing `FINAL_DATE` values on Final shells (mostly legacy blank-status rows whose only completion evidence is an Approved final inspection). `FILE_DATE` and existing `PERMIT_DATE` values were already correct. Active coverage for `PERMIT_DATE` is complete; 236 Final rows still lack a dated Permit Issuance event.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: Martinez, CA (2,000 sample rows)
- Script: `agent/scripts/ca/data_repair_ca_martinez.py`
- Artifact: `AGENT_DATA_PATH/repaired/permits_ca_martinez_repaired.parquet`

## DATA schema

Accela portal payloads with content variants:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `portal_issued_finaled` | 1,333 | Permit Issued + Final Approved / completion date |
| `portal_issued` | 349 | Issued present; no final-completion date |
| `portal_final_insp_only` | 236 | Final evidence without dated Permit Issuance |
| `portal_application_only` | 78 | Top-level / Application Submittal date only |
| `search_data_only` | 4 | Only `search_data` (Date present; Status blank) |

Canonical Accela fields:

| DATA source | Target field |
| --- | --- |
| `status` / `search_data.Status` (+ workflow inference) | `STATUS_NORMALIZED` |
| Earliest of `date` / `search_data.Date` / Application Submittal Submitted* | `FILE_DATE` |
| Earliest Permit Issuance `Permit Issued` | `PERMIT_DATE` |
| Earliest Inspection `Final Approved` (fallback: `Pmt Complete & Apprvd`; then Approved final inspection `Status Date`) | `FINAL_DATE` |

## Findings by field

### STATUS_NORMALIZED

- Before: Final 1,208, null 421, Inactive 200, Active 148, In Review 23.
- When `DATA.status` is present, upstream mapping is correct (`Finaled`→Final, `Issued`→Active, `Expired`/`Withdrawn`/`Revoked`/`CANCELLED`/`Void`→Inactive, `Submitted`/`Plan Review`/`Ready to Issue`→In Review).
- Nulls are blank `DATA.status` / `STATUS_ORIGINAL` (411 blank `search_data.Status`, 10 missing). Inferred from workflow:
  - **FILLED Final** 349 (dated Final Approved / Approved final inspection; includes 207 shells with TBD-only `Pmt Complete & Apprvd` but Approved FINAL inspections)
  - **FILLED Active** 19 (Permit Issued, no completion)
  - **FILLED Inactive** 6 (Expired / Permit Expired marks)
  - **FILLED In Review** 47 (no dated issuance or completion; includes 4 `search_data`-only TMP shells)
- **FIXED** 2:
  - `Fee Estimate` Inactive → In Review
  - `Reactivated` In Review with dated Final Approved → Final
- Did **not** promote `Issued` Active rows to Final from inspections (none of the 148 Issued rows had final evidence).

### FILE_DATE

- Already populated on 2,000 / 2,000 rows.
- Matches `DATA.date` / `search_data.Date` in every comparable row; Application Submittal Submitted dates are never earlier.
- No FILLED / FIXED changes.

### PERMIT_DATE

- Missing 318 / 2,000 before and after. When present and a Permit Issued event exists, values match (0 incorrect among 1,682 comparable rows).
- After repair: Active 167/167 (100%), Final 1,322/1,558 (84.9%), In Review 0/70, Inactive 193/205.
- Unfillable Final gaps are `portal_final_insp_only` legacy shells (no Permit Issuance task history). Four already-Finaled rows also lack Issued events.

### FINAL_DATE

- Missing 655 before → 443 after.
- After repair: Final 1,557/1,558 (99.9%); Active / In Review / Inactive have none.
- Prefer Inspection `Final Approved` (matches existing FINAL_DATE whenever that mark exists). Fallback chain fills Finaled / blank-status finals from `Pmt Complete & Apprvd` or Approved final inspection `Status Date`.
- **FILLED** 212 (including 3 Finaled shells that only had Approved final inspections / dated Pmt Complete, plus blank-status completions).
- One Finaled row (`13BLD-1110`) has only a Denied final inspection and no completion mark → FINAL_DATE stays missing.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 421 | 2 | 421 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 318 → 318 |
| FINAL_DATE | 212 | 0 | 655 → 443 |

Status after repair: Final 1,558, Inactive 205, Active 167, In Review 70.

Chronology after repair: 0 `PERMIT_DATE` < `FILE_DATE`; 0 `FINAL_DATE` < `PERMIT_DATE`.
