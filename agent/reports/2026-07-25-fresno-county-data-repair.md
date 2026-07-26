# Fresno County data repair

**Summary:** First CA-sample jurisdiction without an existing repair script was Fresno County (2,001 rows). DATA is a flat Accela Citizen Access search listing (`citizen_portal` ×1,031) or null (`missing` ×970). Main defect: 143 unmapped status strings left `STATUS_NORMALIZED` null (esp. `Closed Permit`). Two rows had `DATA.Status=Issued` while upstream labeled Final from stale `STATUS_ORIGINAL=closed`. `FILE_DATE` already matched `Application Date` wherever DATA exists. `PERMIT_DATE` and `FINAL_DATE` are entirely missing and cannot be filled — the portal payload exposes no issuance or completion date. Script: `agent/scripts/ca/data_repair_ca_fresno_county.py`. Artifact: `$AGENT_DATA_PATH/fresno_county_repaired_sample.parquet`.

## Sample and schemas

| INFERRED_SCHEMA | n |
| --- | ---: |
| citizen_portal | 1,031 |
| missing | 970 |

Useful `citizen_portal` fields: `Status`, `Application Date`, `Application #`, `Type`, `Agency`, `FOLDERRSN`, `APN`, `Address`. No issued / finaled / closed / completion date keys appear in DATA.

## STATUS_NORMALIZED

Upstream normalization followed `STATUS_ORIGINAL` for most values but left several Accela statuses unmapped. Where DATA is present, `DATA.Status` matches `STATUS_ORIGINAL` on 1,029 / 1,031 rows (case-insensitive). Repair prefers `DATA.Status`, falling back to `STATUS_ORIGINAL` (same vocabulary) so missing-DATA rows can still be filled.

| Issue | Action |
| --- | --- |
| 101 `Closed Permit` with null NORM | FILLED → Final |
| 16 `Permit Issuance or Approval` with null NORM | FILLED → In Review |
| 13 `Internet Incomplete` with null NORM | FILLED → In Review |
| 5 `Permit Rider Attached` with null NORM | FILLED → Active |
| 4 `Permit Application` with null NORM | FILLED → In Review |
| 3 `Dummy` with null NORM | FILLED → Inactive |
| 2 `Issued` in DATA but NORM=Final (`STATUS_ORIGINAL=closed`) | FIXED → Active |
| 1 row with null STATUS_ORIGINAL and null DATA | left missing |

**Repair:** FILLED 142, FIXED 2. Missing 143 → 1.

After repair: Final 1,389, In Review 275, Inactive 208, Active 128, missing 1.

## FILE_DATE

Already populated for all 2,001 rows. On `citizen_portal` rows, `FILE_DATE` matches `Application Date` at calendar-day resolution for every record (1,031 / 1,031). No FILLED/FIXED. Missing-DATA rows have no alternate application date in DATA to validate against.

## PERMIT_DATE

Ideal: present for Active and Final. Field is missing on **all 2,001** rows. DATA contains no issuance / approval date field, so nothing can be filled.

Coverage after repair: Active 0/128 (0%), Final 0/1,389 (0%).

## FINAL_DATE

Ideal: present for Final. Field is missing on **all 2,001** rows. DATA contains no finaled / completion / closed date field, so nothing can be filled.

Coverage after repair: Final 0/1,389 (0%).

## Performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 142 | 2 | 143 → 1 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 2,001 → 2,001 |
| FINAL_DATE | 0 | 0 | 2,001 → 2,001 |

## Why remaining gaps persist

1. **Sparse DATA schema.** The Fresno County scrape stores Accela search-result rows only. Unlike city Accela portals that embed `tasks` / inspection workflow events with dated "Issued" / "Final Inspection Complete" marks, this payload has a single date (`Application Date`).
2. **Null DATA for ~48% of rows.** Those records still carry `STATUS_ORIGINAL` / `FILE_DATE` from upstream processing, but no JSON to recover issuance or final dates.
3. **One orphan status row.** A single record has neither `DATA.Status` nor `STATUS_ORIGINAL`.

Improving `PERMIT_DATE` / `FINAL_DATE` would require a richer Accela detail scrape (workflow tasks / inspections), not further transforms of the current DATA column.
