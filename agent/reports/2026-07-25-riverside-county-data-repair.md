# Riverside County data repair

**Summary:** First CA-sample jurisdiction without an existing repair script was Riverside County (2,001 rows). Tyler EnerGov payloads (`entity` / `details` / `fees`) are consistent (`entity_fees` ×1,905, `entity_fees_reviews` ×96). Main defects: 13 unmapped `Clearances Required` statuses; miscategorized terminal/issued statuses (`Paid` / `Filed` / `Credited` as In Review, `Renewal Due` as In Review, `Administratively Closed` / `Annexed` mislabeled); 6 Issued rows missing `PERMIT_DATE` despite `IssueDate`; 41 spurious `FINAL_DATE` values on non-Final rows. `FILE_DATE` already matched `entity.ApplyDate` for every row. Script: `agent/scripts/ca/data_repair_ca_riverside_county.py`. Artifact: `$AGENT_DATA_PATH/riverside_county_repaired_sample.parquet`.

## Sample and schemas

| INFERRED_SCHEMA | n |
| --- | ---: |
| entity_fees | 1,905 |
| entity_fees_reviews | 96 |

Useful fields (entity preferred; details as fallback): `CaseStatus` / `PermitStatus` (always agree), `ApplyDate`, `IssueDate`, `FinalDate` / `FinalizeDate`. `ExpireDate` is a validity window, not a completion date. `CompleteDate` / `ClosedDate` are unused in this sample.

## STATUS_NORMALIZED

Upstream normalization followed `STATUS_ORIGINAL`, which matches `entity.CaseStatus` on all 2,001 rows. Gaps and miscategorizations relative to the Active / Final / In Review / Inactive contract:

| Issue | Action |
| --- | --- |
| 13 `Clearances Required` with null NORM | FILLED → In Review |
| 158 `Paid` (fee / records-request terminals, almost all with `FinalDate`) labeled In Review | FIXED → Final |
| 17 `Filed` (Survey Corner Record; 15/17 have `FinalDate`) labeled In Review | FIXED → Final |
| 4 `Credited` (mitigation-fee terminals) labeled In Review | FIXED → Final |
| 18 `Renewal Due` (issued Business Stormwater Reg) labeled In Review | FIXED → Active |
| 5 `Annexed` labeled In Review | FIXED → Inactive |
| 2 `Administratively Closed` labeled Final (no `FinalDate`) | FIXED → Inactive |

**Repair:** FILLED 13, FIXED 204. Missing 13 → 0.

After repair: Final 957, Inactive 434, Active 318, In Review 292.

## FILE_DATE

Already populated for all 2,001 rows and matched `entity.ApplyDate` at UTC calendar-day resolution. No FILLED/FIXED.

## PERMIT_DATE

Ideal: present for Active and Final. Where both `PERMIT_DATE` and `IssueDate` exist they always match (1,272 / 1,272).

| Repair | n | Source |
| --- | ---: | --- |
| FILLED | 6 | Issued rows with `IssueDate` but missing `PERMIT_DATE` |
| FIXED | 0 | — |

Remaining Active/Final missing `PERMIT_DATE` after repair: **332** (all Final: mostly `Completed` ×109 and `Final` ×56 with `Issued=False` and no `IssueDate`, plus remapped `Paid` / `Filed` / `Credited` fee or survey cases that never issued). No alternate issuance field exists in DATA.

Coverage after repair: Active 318/318 (100%), Final 625/957 (65.3%).

## FINAL_DATE

Ideal: present for Final. Existing finals always matched `entity.FinalDate` (= `details.FinalizeDate`) when present.

| Repair | n |
| --- | ---: |
| FILLED | 0 |
| FIXED (cleared on non-Final) | 41 |

Clears: Void ×25, History ×4, Approved ×4, Annexed ×5, Issued ×1, Canceled ×1, Refunded ×1. Remaps of Paid / Filed / Credited to Final retained their existing `FINAL_DATE` values (already correct vs `FinalDate`).

Remaining Final without `FINAL_DATE`: **5** (`Paid` / `Filed` / `Credited` shells with null `FinalDate`).

Coverage after repair: Final 952/957 (99.5%); Active / In Review / Inactive all 0% (spurious finals cleared).

## Performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 13 | 204 | 13 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 6 | 0 | 729 → 723 |
| FINAL_DATE | 0 | 41 | 1,008 → 1,049 |

Missing `FINAL_DATE` rises because 41 spurious non-Final finals were cleared; remapped Finals already had dates so no new fills offset that.

## Why remaining gaps persist

1. **Final / Completed without issuance.** Many completed building / tract / landscape cases carry `FinalDate` but never recorded `IssueDate` (`details.Issued=False`). Status advanced to Final/Completed without a dated issuance event in the EnerGov payload.
2. **Fee and records-request terminals.** `Paid` / `Credited` mitigation-fee and records-request cases often finalize without ever issuing a permit, so `PERMIT_DATE` stays missing even after status → Final.
3. **No dated final on a few remapped terminals.** Five Paid / Filed / Credited rows have null `FinalDate` / `FinalizeDate`.

**Bottom line:** Riverside County’s EnerGov scrape is date-consistent where fields exist (`ApplyDate` / `IssueDate` / `FinalDate` match the normalized columns exactly). Remaining gaps are missing agency fields, not mismatched ones; the repair work is mostly status reclassification and clearing `FINAL_DATE` off non-Final rows.
