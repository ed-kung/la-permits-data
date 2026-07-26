# Aliso Viejo data repair

**Summary:** Albany (CA) is the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script, but all 2,000 Albany rows have null `DATA`, so agency-JSON repair is impossible. The next uncovered jurisdiction with usable `DATA` is Aliso Viejo (2,000 rows). Its Tyler EnerGov portal payloads (`portal_fees` ×1,652, `portal_full` ×348) show stale `STATUS_ORIGINAL`-driven labels (54 mismatches vs `CaseStatus`), systematically wrong `FILE_DATE` / `PERMIT_DATE` / `FINAL_DATE` vs `ApplyDate` / `IssueDate` / `FinalDate` on ~150 rows each, plus fillable Final gaps. After repair: `FILE_DATE` 100%; Active `PERMIT_DATE` 100%; Final `PERMIT_DATE` 99.9% and `FINAL_DATE` 100%; no spurious `FINAL_DATE` on non-Final rows. Script: `agent/scripts/ca/data_repair_ca_aliso_viejo.py`. Artifact: `$AGENT_DATA_PATH/aliso_viejo_repaired_sample.parquet`.

## Scope note: Albany skipped

Going down sorted `(STATE, JURISDICTION)` pairs, the first missing script is `data_repair_ca_albany.py`. Albany’s sample has `DATA` null on every row (`STATUS_ORIGINAL` values like `complt` / `issued` / `project finaled` exist, but no raw JSON). Without `DATA`, the required field assessment against agency source fields cannot be performed. Work continued with **Aliso Viejo**.

## DATA schemas

| INFERRED_SCHEMA | n | Top-level keys |
| --- | ---: | --- |
| `portal_fees` | 1,652 | entity, details, fees, contacts, processing_status |
| `portal_full` | 348 | portal_fees + reviews, holds, attachments, more_info |

Canonical fields live under `entity` (fallback `details`):

| Field | DATA source |
| --- | --- |
| STATUS_NORMALIZED | `CaseStatus` / `PermitStatus` |
| FILE_DATE | `ApplyDate` |
| PERMIT_DATE | `IssueDate` |
| FINAL_DATE | `FinalDate` / `FinalizeDate` |

## STATUS_NORMALIZED

No missing statuses. Upstream normalized from stale `STATUS_ORIGINAL` while live `CaseStatus` had advanced:

| CaseStatus | Wrong current label(s) | Expected | n |
| --- | --- | --- | ---: |
| Complete | Active / Inactive / In Review | Final | 27 |
| Issued | In Review / Inactive | Active | 10 |
| Expired | Active | Inactive | 6 |
| Stop Work Order | In Review | Inactive | 8 |
| Fees Due | Inactive | In Review | 3 |

**Repair:** 54 FIXED. After: Final 970, Active 589, Inactive 247, In Review 194.

Status map additions beyond Arcadia-style EnerGov basics: `Submitted`, `Submitted - Online`, `Fees Due`, `Fees Paid` → In Review; `Cancelled`, `Denied`, `Plan Approval Expired`, `Stop Work Order` → Inactive.

## FILE_DATE

Already populated for all 2,000 rows. **157** disagree with `ApplyDate` (upstream date is 1–27 days earlier; no alternate matching timestamp exists anywhere in `DATA`). Not a timezone artifact (UTC vs Pacific does not explain the gap).

**Repair:** 157 FIXED → ApplyDate. Coverage remains 100%.

## PERMIT_DATE

- 8 Active/Final-eligible rows missing `PERMIT_DATE` despite `IssueDate` → FILLED (mostly stale In Review labels remapped to Issued/Complete).
- ~155 rows where `PERMIT_DATE` ≠ `IssueDate` → FIXED (same systematic offset pattern as FILE_DATE).
- 1 Complete row with `Issued=False` and null `IssueDate` → left missing.

After repair by status: Active 589/589 (100%), Final 969/970 (99.9%). Residual missing count drops 253 → 245 (remaining gaps are In Review / Inactive without issuance, which is acceptable).

## FINAL_DATE

- 27 Complete rows (mostly mislabeled Active/Inactive/In Review) had `FinalDate` but null `FINAL_DATE` → FILLED after status fix.
- ~130 Final rows where `FINAL_DATE` ≠ `FinalDate` → FIXED.
- 4 spurious `FINAL_DATE` values on Void/Cancelled → cleared (FIXED).

After repair: Final 970/970 (100%); Active / In Review / Inactive all 0%.

Two `Issued` rows carry `details.FinalizeDate` with null `entity.FinalDate`; CaseStatus remains Issued → correctly left Active without `FINAL_DATE`.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 54 | 0 → 0 |
| FILE_DATE | 0 | 157 | 0 → 0 |
| PERMIT_DATE | 8 | 155 | 253 → 245 |
| FINAL_DATE | 27 | 134 | 1,053 → 1,030 |

Net missing `FINAL_DATE` / `PERMIT_DATE` falls mainly because clears of wrong non-Final finals and status remaps outweigh residual In Review / Inactive gaps (which should stay empty for `FINAL_DATE`).

## Artifacts

- Script: `agent/scripts/ca/data_repair_ca_aliso_viejo.py`
- Repaired sample: `$AGENT_DATA_PATH/aliso_viejo_repaired_sample.parquet`
