# Inglewood data repair — field assessment

**Summary:** Inglewood’s 2,000 sample records split into an Accela `tasks` schema (558) and a minimal `flat` listing schema (1,442), consistent with two upstream feeds merged without deduplication (same pattern as Culver City). `FILE_DATE` is already complete. Most quality issues are in `tasks`: 92 missing statuses (mainly Pre-Sale `Report Sent`), 5 `Issued` Solar permits wrongly labeled Final with fabricated `FINAL_DATE`s, and missing `PERMIT_DATE` for Pre-Sale `Issued` / some Finaled Solar rows. The flat schema has no status or workflow dates in `DATA`, so 1,424 missing statuses cannot be filled. The sample contains 4 cross-schema duplicate pairs (by `permit_no`) plus 53 within-flat exact duplicates. Repair script: `agent/scripts/inglewood_data_repair.py`.

## Data source

- Input: `MY_DATA_PATH/processed_data/permits_la_sample.parquet`
- Filter: `JURISDICTION == "Inglewood"` (n=2,000)
- Schemas:
  - `tasks` (558): Accela Citizen Access (`date`, `status`, `tasks`, `record_type`, `search_data`, …). Event keys use spaced names (`'Marked as '`, `' on '`). Record types: Pre-Sale, Solar Permit, Fire Permit.
  - `flat` (1,442): listing scrape with only `date`, `address`, `parcel_no`, `permit_no`, `valuation`, `description`.

## Field assessment

### STATUS_NORMALIZED

| Issue | Count | Cause |
| --- | --- | --- |
| Missing (`tasks`) | 92 | `Report Sent` (81) and some `Submitted` (10) never mapped; 1 Fire Permit with blank `status` |
| Incorrect (`tasks`) | 5 | `DATA.status=Issued` but `STATUS_NORMALIZED=Final` (Solar permits; Inspection still TBD) |
| Missing (`flat`) | 1,424 | No status field in `DATA`; unfillable |

`tasks` mapping from `DATA.status`:

| Raw status | Normalized |
| --- | --- |
| Finaled, Report Sent | Final |
| Issued | Active |
| Expired | Inactive |
| Submitted, Ready to Issue, Plan Review, Pending, (blank) | In Review |

`Report Sent` is Pre-Sale-only and means the pre-sale report was completed/sent → Final.

### FILE_DATE

- Missing: 0 / 2,000
- For all 558 `tasks` records, `FILE_DATE` equals `DATA.date`
- 9 `flat` rows differ from `DATA.date` by 1–28 days; in those cases `DATA.date` matches `PERMIT_DATE` when present, so `date` looks like an issue date while `FILE_DATE` looks like the application date from another source — **not overwritten**
- **No repair needed**

### PERMIT_DATE

| Status (before) | Present | Notes |
| --- | --- | --- |
| Active | 33 / 86 (38%) | 53 Pre-Sale `Issued` lack Permit Issuance events |
| Final | 73 / 76 (96%) | 3 Finaled Solar omit Permit Issuance |
| In Review | 0 / 317 | Expected |
| Inactive | 4 / 5 | Optional |

**Sources / causes:**
1. Primary: `Permit Issuance` → `Issued` (matches existing `PERMIT_DATE` for all 92 rows that have the event).
2. Pre-Sale `Issued` has no Permit Issuance task; fill from `Review Application` → `Approved` (equals `FILE_DATE` for all 53).
3. Finaled Solar without issuance: fill from `Plans Coordination` → `Ready to Issue` when present (2 of 3).
4. Pre-Sale `Report Sent` (Final after repair, n=81): no Review Application or Permit Issuance events — left missing (no reliable issuance date in `DATA`).
5. 1 Finaled Solar has only an Inspection event — unfillable.

### FINAL_DATE

| Status (before) | Present | Notes |
| --- | --- | --- |
| Final | 75 / 76 (99%) | 1 flat Final unfillable |
| Active | 0 / 86 | — |
| In Review | 2 / 317 | Spurious; plus 10 missing-status Submitted with FINAL |

**Sources / causes:**
1. Finaled: `Inspection` → `Final Inspection Complete` (agrees with existing FINAL for 56/57; one record has two finals events — keep first).
2. Report Sent: prefer latest `Pre-Sale Report` → `Sent`; 9 existing FINAL values used an earlier Inspection/Completed date → **FIXED**.
3. 5 Issued→Final Solar rows have `FINAL_DATE` values that do **not appear anywhere** in `DATA` → clear after status fix to Active.
4. 12 Submitted rows carry spurious `FINAL_DATE` (mostly absent from JSON; two match mid-workflow Inspection dates) → clear once status is In Review.

## Repair results (`data_repair`)

| Field | FILLED | FIXED | Missing before → after |
| --- | --- | --- | --- |
| STATUS_NORMALIZED | 92 | 5 | 1,516 → 1,424 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 55 | 0 | 1,890 → 1,835 |
| FINAL_DATE | 0 | 26 | 1,832 → 1,849 |

Missing `FINAL_DATE` rises because 17 spurious non-Final dates were cleared; remaining Final coverage is 151 / 152 (99.3%).

After repair (by status):

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | --- | --- | --- | --- |
| Active | 91 | 91 (100%) | 91 (100%) | 0 (0%) |
| Final | 152 | 152 (100%) | 70 (46.1%) | 151 (99.3%) |
| In Review | 328 | 328 (100%) | 0 (0%) | 0 (0%) |
| Inactive | 5 | 5 (100%) | 4 (80%) | 0 (0%) |
| (missing, all flat) | 1,424 | 1,424 (100%) | 0 | 0 |

`INFERRED_SCHEMA`: `flat` 1,442; `tasks` 558.

## Two data feeds and potential duplicates

Like Culver City, the two schemas appear to come from separate upstream feeds that the third-party vendor merged without deduplication:

| Feed | Likely source | Shape |
| --- | --- | --- |
| `tasks` (558) | Per-record Accela Citizen Access portal scrapes | Same rich key set as Culver City `tasks` (`tasks`, `status`, `search_data`, HTML `details`, named reviewers) |
| `flat` (1,442) | Bulk listing / search-results scrape | Only `date`, `address`, `parcel_no`, `permit_no`, `valuation`, `description` — thinner than Culver City’s structured flat export (`RecordStatus`, `DateOpened`, …) |

**Partial type bifurcation (unlike Culver City’s full overlap):**
- `tasks` is dominated by Pre-Sale (445), Solar (91), and Fire (22).
- `flat` is almost all `BLD*` building listings; ~88 solar-like and ~37 fire-like by description, plus ~1,316 other building work.
- Pre-Sale is effectively `tasks`-only (flat descriptions almost never mention pre-sale).
- Solar/Fire appear in **both** feeds across overlapping years (2019–2024), so the feeds are not cleanly partitioned by type or date.
- `STATUS_ORIGINAL` / `RECORD_TYPE_ORIGINAL` are populated for ~99% of `tasks` rows but missing for ~99% of `flat` rows — further evidence the flat feed never went through the same status/type enrichment.

**Cross-schema duplicates:** 4 pairs in the 2,000-row sample match exactly on `permit_no` (3 Solar, 1 Fire). In each pair:
- Same address and (nearly) same description.
- `tasks` has `STATUS_NORMALIZED` + `PERMIT_DATE`; `flat` has neither.
- Coverage is complementary, same as Culver City.

Example: `BLD24-02445` — flat `FILE_DATE=2024-06-27` equals tasks `PERMIT_DATE`, while tasks `FILE_DATE=2024-06-06`, reinforcing that flat `date` is sometimes an issue date.

Given sampling probability ~`(2000/N)^2` per pair, the full dataset likely has substantially more cross-schema duplicates. This should be checked at full-data scale (match on `permit_no`, with STREET+FILE_DATE+description as backup).

**Within-flat duplicates:** 53 `permit_no` keys appear twice (106 rows). All 53 pairs have **identical** `DATA` JSON; 52/53 have STREET filled on exactly one copy and null on the other. These look like double-ingestion of the same listing record (possibly one pass with address geocoding and one without), not two different permits.

## Artifacts

- Repair function: `agent/scripts/inglewood_data_repair.py` (`data_repair`)
