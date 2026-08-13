# Palmetto Bay (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (first-seen `(JURISDICTION, STATE)` order) was **Palmetto Bay**. DATA is the Accela-style portal family shared with North Miami (`main.Status` / `Applied` / `Issued` / `Approved` / `Final`). Upstream mostly matched agency status and dates; the main defects were stale `STATUS_ORIGINAL` (issued/pending kept after portal moved to final/canceled/issued), null status on one Final row, missing `PERMIT_DATE` on `approved` (and a few issued/Final) rows where only `Approved` was populated, and spurious `FINAL_DATE` on canceled Inactive rows copied from `main.Final`. After repair: STATUS 100%; FILE_DATE 100%; Active/Final PERMIT_DATE 99.9%; Final FINAL_DATE 100%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Palmetto Bay, FL** → `agent/scripts/fl/data_repair_fl_palmetto_bay.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

All 2,000 rows share the same top-level Accela key set (`main`, `details`, `actions`, `fees`, …). Content variants are labeled `accela_{status}_{date_suffix}`:

| Schema | n | Notes |
| --- | ---: | --- |
| `accela_final_issued_finaled` | 1,600 | Issued + Final dates |
| `accela_issued_issued` | 168 | Issued, not finaled |
| `accela_pending_applied` | 139 | Applied only |
| `accela_canceled_finaled` | 38 | Canceled with Final stamp |
| `accela_approved_approved` | 22 | Approved, blank Issued |
| `accela_canceled_issued_finaled` | 15 | Canceled after issue + Final |
| `accela_expired_issued` | 8 | Expired with Issued |
| `accela_final_finaled` | 4 | Final date, blank Issued |
| `accela_canceled_applied` / `_issued` | 5 | Canceled early |
| `accela_shell` | 1 | Empty `main` (LIEN SEARCH) |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `main.Status` (`final`→Final; `issued`/`approved`→Active; `pending`→In Review; `canceled`/`expired`→Inactive) |
| FILE_DATE | `main.Applied` |
| PERMIT_DATE | `main.Issued`, else `main.Approved`, else completed issue/`collissue` action |
| FINAL_DATE | `main.Final`, else completed `final - FINALIZE PERMIT` action |

Agency status → normalized (from `main.Status`):

| Agency status | → | n |
| --- | --- | ---: |
| final | Final | 1,604 |
| issued | Active | 168 |
| pending | In Review | 139 |
| canceled | Inactive | 58 |
| approved | Active | 22 |
| expired | Inactive | 8 |
| (blank main) | — | 1 |

## Field assessments

### STATUS_NORMALIZED

| Upstream | n | Assessment |
| --- | ---: | --- |
| Final | 1,599 | Correct vs agency `final` (plus 1 shell kept Final) |
| Active | 194 | 188 correct; **6 wrong** (5 agency already `final`, 1 `canceled`) |
| In Review | 141 | 139 correct (`pending`); **2 wrong** (agency `approved` / `issued`) |
| Inactive | 65 | Correct (`canceled` / `expired`) |
| null | 1 | Fillable: agency `final` |

**Root cause:** Upstream normalized from stale `STATUS_ORIGINAL` on 8 rows while `main.Status` had already advanced (issued→final, issued→canceled, pending→approved/issued). One older Final row (`SRP-2011-0029`) had null `STATUS_ORIGINAL` / `STATUS_NORMALIZED` despite a complete `main` block.

**Repair performance:** FILLED 1; FIXED 8; missing 1 → 0. After: Final 1,605; Active 190; In Review 139; Inactive 66.

### FILE_DATE

Ideal: populated for all records (application / submittal).

- Before: present on **1,999 / 2,000**; 1,998 matched `main.Applied`. The missing row (`SRP-2011-0029`) had Applied `01/21/2011`. The empty-main shell retained an upstream FILE_DATE that cannot be re-derived from DATA.
- **1 FILLED, 0 FIXED.**
- After: labeled rows 100% across Active / Final / In Review / Inactive (shell unchanged).

### PERMIT_DATE

Ideal: populated for Active and Final.

- Before: **1,789 / 2,000** present; among 1,793 rows with `Issued`, 1,788 matched Issue Date. Gaps were concentrated on `approved` Active rows (blank Issued, Approved present) and a handful of issued/Final rows where Issued existed but PERMIT_DATE was null, plus 4 Final rows with blank Issued.
- **44 FILLED, 0 FIXED** (39 from Approved, 5 from Issued). Missing 211 → 167 (remaining mostly In Review 139 + Inactive without issue/approval 27 + 1 Final).
- After: Active **190 / 190 (100%)**; Final **1,604 / 1,605 (99.9%)** — remaining gap is a 40-year recertification Final with blank Issued and Approved (only Final date). In Review **0%**. Inactive **39 / 66 (59.1%)** when Issued/Approved exist.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: Final missing FINAL on **0 / 1,599**; **52** Inactive (`canceled`) incorrectly carried `main.Final` as FINAL_DATE; 5 Active→Final status fixes lacked FINAL_DATE despite `main.Final`.
- **6 FILLED** (status corrections to Final); **52 FIXED** (cleared on Inactive). Missing 349 → 395 (net clear of spurious non-Final finals).
- After: Final **1,605 / 1,605 (100%)**; non-Final **0%**.

**Note:** No `PERMIT_DATE > FINAL_DATE` or `FILE_DATE > PERMIT_DATE` inversions after repair. Canceled rows are left Inactive even when `main.Final` is populated (portal cancel after a final stamp); those Final stamps are cleared from `FINAL_DATE`.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 1 | 8 | 1 → 0 |
| FILE_DATE | 1 | 0 | 1 → 0 |
| PERMIT_DATE | 44 | 0 | 211 → 167 |
| FINAL_DATE | 6 | 52 | 349 → 395 |

Post-repair coverage by status:

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Active | 190 | 100% | 100% | 0% |
| Final | 1,605 | 100% | 99.9% | 100% |
| In Review | 139 | 100% | 0% | 0% |
| Inactive | 66 | 100% | 59.1% | 0% |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_palmetto_bay.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/repaired/permits_fl_palmetto_bay_repaired.parquet`
