# South Miami (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script was **South Miami**. DATA is an Accela / eTRAKiT portal payload (`permit_info` / `inspections` / `search_data`). Upstream STATUS mostly matched `PermitStatus`, with a few lags (FINALED labeled Active; ISSUED labeled In Review) and one unmapped status (`REVISION IN CHECK`). Repair FILLED 1 and FIXED 10 STATUS values (0 null remaining). FILE_DATE already matched `PermitAppliedDate` on 2,000/2,001 rows. PERMIT_DATE filled 39 missing Issued/Approved stamps (Active 100% / Final 98.2%). FINAL_DATE filled 1,036 Closed/certificate shells from `PermitFinaledDate` or passed inspections (Final 96.6%); non-Final FINAL_DATE cleared via status override to Final when finaled was present.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` (first-appearance order) were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **South Miami, FL** → `agent/scripts/fl/data_repair_fl_south_miami.py` (2,001 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All 2,001 rows share Accela top-level keys `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`. Content suffixes split by which canonical `permit_info` dates are populated:

| Schema | n | Notes |
| --- | ---: | --- |
| `accela_issued` | 1,329 | Issued, no PermitFinaledDate (many CLOSED finals) |
| `accela_issued_finaled` | 422 | Issued + Finaled |
| `accela_applied` | 205 | Applied only (plan check / under review / some voids) |
| `accela_approved` | 35 | Approved only (no issued/finaled) |
| `accela_finaled` | 9 | Finaled, no issued |
| `accela_status_only` | 1 | Status present, no dates |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (override to Final when `PermitFinaledDate` set) |
| FILE_DATE | `permit_info.PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` for Active/Final |
| FINAL_DATE | `PermitFinaledDate` → latest passed final-ish inspection → latest passed inspection; Final only |

Status bases → normalized: CLOSED / FINALED / CO ISSUED / CC ISSUED / CERTIFICATE ISSUED / CERTIFIED / ADMINISTRATIVELY CLOSED → Final; ISSUED / APPROVED → Active; UNDER REVIEW / PLAN CHECK / REVISION IN CHECK → In Review; VOID / EXPIRED / DENIED → Inactive.

## Field assessments

### STATUS_NORMALIZED

| PermitStatus | n | Upstream STATUS_NORMALIZED | Assessment |
| --- | ---: | --- | --- |
| CLOSED | 1,080 | Final 1,080 | Correct |
| FINALED | 410 | Final 406 / Active 4 | 4 lagged as Active |
| ISSUED | 172 | Active 169 / In Review 3 | 3 lagged as In Review |
| VOID | 118 | Inactive 118 | Correct |
| APPROVED | 71 | Active 71 | Correct (2 also carry PermitFinaledDate → repair to Final) |
| UNDER REVIEW | 47 | In Review 47 | Correct |
| PLAN CHECK | 40 | In Review 40 | Correct |
| EXPIRED | 39 | Inactive 39 | Correct |
| CERTIFIED / CO / CC / CERTIFICATE / ADMIN CLOSED | 21 | Final 21 | Correct |
| DENIED | 2 | Inactive 2 | Correct |
| REVISION IN CHECK | 1 | null 1 | Unmapped upstream |

**Root causes:**
- **STATUS_ORIGINAL lag:** Upstream normalized from a stale snapshot (`issued` / `approved` / `under review`) while `PermitStatus` had already advanced to FINALED or ISSUED.
- **Unmapped status:** `REVISION IN CHECK` (post-issuance revision in plan check) was absent from the upstream normalizer → In Review.
- **Finaled-date override:** 2 APPROVED + 1 ISSUED shells already carried `PermitFinaledDate` (and FINAL_DATE) while still labeled Active → treated as Final.

**Repair performance:** FILLED 1, FIXED 10; missing 1 → 0. After: Final 1,514; Active 240; Inactive 159; In Review 88.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **1 missing** (CERTIFIED shell with blank `PermitAppliedDate`; no alternate application stamp in DATA).
- All other 2,000 rows equal `PermitAppliedDate` at calendar-day resolution (**0 FILLED / 0 FIXED**).
- Coverage after repair: Active / In Review / Inactive 100%; Final 99.9%.
- 2 source-level FILE > PERMIT inversions remain (agency `PermitAppliedDate` after `PermitIssuedDate` on FINALED renewals); not inventable from DATA.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Existing values matched `PermitIssuedDate` whenever both present (**0 calendar mismatches**).
- **39 FILLED:** 7 from Issued (including ISSUED shells previously labeled In Review) + 32 from Approved fallback on Active/Final APPROVED / CERTIFIED shells.
- **28 Final** remain without PERMIT_DATE: CLOSED (21) / FINALED (6) / CERTIFIED (1) with blank Issued and Approved.

Coverage after repair: Active 240/240 (100%); Final 1,486/1,514 (98.2%); In Review 1/88 (REVISION IN CHECK keeps Issued stamp); Inactive 56/159 (35.2%, mostly Expired plus Void with prior issuance).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- All already-populated FINAL_DATE values matched `PermitFinaledDate` (**0 mismatches** among the 427 present before repair).
- **1,036 FILLED:** 4 from `PermitFinaledDate` on status-corrected Finals + 1,032 from passed inspections on CLOSED / certificate shells that lacked `PermitFinaledDate` (final-ish Type preferred, else any APPROVED inspection on/after Issued).
- Non-Final correctly have no FINAL_DATE after repair (Active shells with finaled dates were reclassified to Final rather than cleared).
- **51 Final** remain without FINAL_DATE: CLOSED (42) / ADMINISTRATIVELY CLOSED (2) / CERTIFIED (7) with blank Finaled and no usable passed inspections (empty list, CANCELLED, or DISAPPROVED only).

Coverage after repair: Final 1,463/1,514 (96.6%); Active / In Review / Inactive 0%. Date-order inversions: PERMIT>FINAL 0; FILE>PERMIT 2 (source); FILE>FINAL 0 among filled pairs with both dates.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1 | 10 | 1 → 0 |
| FILE_DATE | 0 | 0 | 1 → 1 |
| PERMIT_DATE | 39 | 0 | 257 → 218 |
| FINAL_DATE | 1,036 | 0 | 1,574 → 538 |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_south_miami.py`
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_south_miami_repaired.parquet`
