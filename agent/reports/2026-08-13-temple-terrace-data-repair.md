# Temple Terrace (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (first-seen `(JURISDICTION, STATE)` order) was **Temple Terrace**. DATA is the city permit-portal family shared with Lake Worth Beach / Jacksonville Beach (`permit_status_detail` + `insp_status_detail`, or fees-only `detail`). Upstream mostly labeled status correctly but kept 14 rows Active from a stale `STATUS_ORIGINAL` of "permit printed" while `Status for Permit Number` was already CLOSED / C.O. ISSUED / FINAL INSPECTION COMPLETE; 44 null statuses (mostly plan-check shells) were fillable. `FILE_DATE` already matched `Application Date` on all 2,000 rows. `PERMIT_DATE` had been copied from portal `Permit Date` (admin/closeout stamp) instead of `Issue Date` — 1,835 FIXED. `FINAL_DATE` gaps on Final rows with `COMPLETED` close-out inspections were filled; after repair: STATUS 100%; FILE_DATE 100%; Active/Final PERMIT_DATE 98.6%; Final FINAL_DATE 96.8%.

## Jurisdiction selection

`(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` were checked against `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing: **Temple Terrace, FL** → `agent/scripts/fl/data_repair_fl_temple_terrace.py` (2,000 sample rows).

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Notes |
| --- | ---: | --- |
| `permit_status` | 1,957 | `permit_status_detail` + `insp_status_detail` (+ fees) |
| `fees_detail` | 43 | `detail` + `fees` + `fees_total` only (no issue/inspections) |

Canonical fields:

| Target field | Source in DATA |
| --- | --- |
| STATUS_NORMALIZED | `Status for Permit Number` on `permit_status_detail`; else `Application Status` on `detail` (Inactive app statuses override) |
| FILE_DATE | `Application Date` |
| PERMIT_DATE | `Issue Date` (not portal `Permit Date`) |
| FINAL_DATE | Latest successful inspection (`APPROVED` / `COMPLETED` / `APPROVED WITH EXCEPTION` / `PARTIALLY APPROVED` / `WAIVED`), excluding Notice of Commencement |

Agency status → normalized (dominant values):

| Agency status | → | n (permit_status) |
| --- | --- | ---: |
| CLOSED | Final | 1,690 |
| PERMIT PRINTED | Active | 197 |
| C.O. ISSUED | Final | 44 |
| FINAL INSPECTION COMPLETE | Final | 19 |
| PERMIT REVOKED | Inactive | 7 |

`fees_detail` Application Status: IN PLAN CHECK → In Review; APPROVED → In Review; CLOSED / COMPLETE/CLOSED BY REPORT → Final; VOID → Inactive.

## Field assessments

### STATUS_NORMALIZED

| Upstream | n | Assessment |
| --- | ---: | --- |
| Final | 1,739 | Correct vs agency CLOSED / C.O. / FINAL INSPECTION COMPLETE |
| Active | 210 | 196 correct (PERMIT PRINTED); **14 wrong** (agency already Final) |
| Inactive | 7 | Correct (PERMIT REVOKED) |
| null | 44 | Fillable: 31 In Review, 11 Final, 1 Active, 1 Inactive |

**Root cause:** Upstream normalized from stale `STATUS_ORIGINAL` ("permit printed") on 14 rows whose `Status for Permit Number` had moved to CLOSED / C.O. ISSUED / FINAL INSPECTION COMPLETE. All 43 `fees_detail` rows (plus one `permit_status` PERMIT PRINTED with null original) left `STATUS_NORMALIZED` null despite usable Application / Permit status strings.

**Repair performance:** FILLED 44; FIXED 14; missing 44 → 0. After: Final 1,764; Active 197; In Review 31; Inactive 8.

### FILE_DATE

Ideal: populated for all records (application / submittal).

- Before: present on **2,000 / 2,000**; all matched `Application Date` (1,957 from `permit_status_detail`, 43 from `detail`).
- **0 FILLED, 0 FIXED.**
- After: labeled rows 100% across Active / Final / In Review / Inactive.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Before: **1,956 / 2,000** present; among 1,934 rows with `Issue Date`, only **121** matched Issue Date — the rest matched portal `Permit Date` (median +152 days after Issue; up to +8,884 days). That stamp is a later admin/closeout date, not issuance.
- **0 FILLED, 1,835 FIXED** (realign to Issue Date or clear Permit-Date-only stamps when Issue blank). Missing 44 → 66.
- After: Active **188 / 197 (95.4%)**; Final **1,745 / 1,764 (98.9%)** — remaining gaps have blank `Issue Date` (9 PERMIT PRINTED, 8 CLOSED) or are `fees_detail` Final shells (11) with no issue block. In Review **0%**. Inactive **1 / 8** (only one revoked row has Issue Date).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Before: Final missing FINAL on **179 / 1,739**; non-Final had none. Upstream often ignored `COMPLETED` close-out inspections (`EXPIRED PERMIT/CLOSE NO INSP`, `CLOSE PERMIT NO INSP REQUIRED`, …).
- **147 FILLED, 23 FIXED** (later successful non-NOC inspection). Missing 440 → 293.
- After: Final **1,707 / 1,764 (96.8%)**; non-Final **0%**. Remaining 57 Final gaps: 40 empty `insp_status_detail`, 6 with only DISAPPROVED / NOC / non-success rows, 11 `fees_detail` shells — no usable completion signal (portal `Permit Date` is often a batch stamp such as 04/01/11 and is not used).

**Note:** One agency quirk has `Issue Date` one day after Application Date; one has MECH FINAL three days before Issue Date — left as reported in DATA.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 44 | 14 | 44 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 1,835 | 44 → 66 |
| FINAL_DATE | 147 | 23 | 440 → 293 |

Coverage after repair (by effective status):

| Status | n | FILE_DATE | PERMIT_DATE | FINAL_DATE |
| --- | ---: | ---: | ---: | ---: |
| Final | 1,764 | 100% | 98.9% | 96.8% |
| Active | 197 | 100% | 95.4% | 0% |
| In Review | 31 | 100% | 0% | 0% |
| Inactive | 8 | 100% | 12.5% | 0% |

Alignment checks: `FILE_DATE == Application Date` 2,000 / 2,000; `PERMIT_DATE == Issue Date` 1,934 / 1,934 when Issue present.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_temple_terrace.py`
- Repaired sample parquet: `$AGENT_DATA_PATH/repaired/permits_fl_temple_terrace_repaired.parquet`
