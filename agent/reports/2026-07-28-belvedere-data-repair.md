# Belvedere (CA) data repair — 2026-07-28

Belvedere was the first CA jurisdiction in `permits_ca_sample.parquet` without an existing repair script. STATUS_NORMALIZED had 57 nulls from unmapped portal statuses (50 fillable); FILE_DATE and PERMIT_DATE already matched `Permit Date` / `Issued Date` when present; all 82 FINAL_DATE values were incorrectly copied from `CTL Expiration Date` and were cleared. No true finalization date exists in DATA.

## Scope

- Input: `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`
- Jurisdiction: Belvedere, CA (2,000 sample rows)
- Script: `agent/scripts/ca/data_repair_ca_belvedere.py`
- Artifact: `AGENT_DATA_PATH/belvedere_repaired_sample.parquet`

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Distinguishing keys |
| --- | ---: | --- |
| `portal_reviews` | 1,931 | `reviews` (always empty in sample) |
| `portal_plan_reviews_rtype` | 64 | `plan_reviews` + `record_type_from_contractor_box` |
| `portal_plan_reviews` | 5 | `plan_reviews` only |

All variants share core fields: `Status`, `Permit Date`, `Issued Date`, `CTL Expiration Date`, `Permit Number`, plus empty `inspections` / fee / payment shells.

## Field findings

### STATUS_NORMALIZED

Before: Active 1,510 / Final 331 / In Review 48 / Inactive 54 / null 57.

Nulls came from portal statuses the upstream mapper skipped (`Review-First/Second/Third`, `Comments Sent/Generated`, `Approved as Essential`, `Final-ReVal Required`, `Building Final-Planning Required`, `Cancelled & Refunded`, `Pmt Reminder sent`, `Set for Hearing`) plus 7 blank-`Status` shells.

Repair filled 50 rows. Mapping highlights: Review/Comments/Pending-payment/hearing → In Review; Approved as Essential / Building Final-Planning Required → Active; Final-ReVal Required → Final; Cancelled & Refunded → Inactive. Seven blank-Status rows remain null.

After: Active 1,513 / Final 333 / In Review 92 / Inactive 55 / null 7. No FIXED status changes (mapped rows were already correct).

### FILE_DATE

`FILE_DATE` equals DATA `Permit Date` for 1,999/2,000 rows. One empty-shell record has no dates. No fills or fixes.

### PERMIT_DATE

`PERMIT_DATE` equals DATA `Issued Date` wherever Issued Date is present (1,823 rows; 0 mismatches). Missing PERMIT_DATE on Active/Final (41 + 9 before status fill) coincides with empty Issued Date; `Permit Date` is the application date and was not used as a substitute. Coverage after repair: Active 97.3%, Final 97.3%.

### FINAL_DATE

All 82 populated FINAL_DATE values (59 Final + 23 non-Final) equal `CTL Expiration Date` — a construction-time-limit expiry, not a completion/signoff date. Inspections and reviews are empty, so no alternate final date exists. Repair cleared all 82 (FIXED). Final rows remain without FINAL_DATE.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 50 | 0 | 57 → 7 |
| FILE_DATE | 0 | 0 | 1 → 1 |
| PERMIT_DATE | 0 | 0 | 177 → 177 |
| FINAL_DATE | 0 | 82 | 1,918 → 2,000 |

## Not repairable

- Blank-Status shells (7) and the one date-empty shell.
- Active/Final without Issued Date (~50) — no issuance timestamp in DATA.
- All Final records for FINAL_DATE — CTL expiry is not a finalization date; no inspections/completion field is populated.
