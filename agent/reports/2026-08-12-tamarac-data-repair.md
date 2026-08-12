# Tamarac (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Tamarac was first. Its DATA is the city-portal family shared with Ormond Beach / St. Petersburg (`detail` + optional `permit_status_detail` / inspections, plus sparse `fees_detail` and `mini_set` shells). Upstream left **399** STATUS_NORMALIZED null and copied portal **Permit Date** into PERMIT_DATE (a close-adjacent stamp on Final rows, not issuance). After repair: status complete (FILLED 399 · FIXED 109); PERMIT_DATE aligned to **Issue Date** (FILLED 25 · FIXED 1,578); FINAL_DATE filled/fixed from inspections and post-issue Permit Date (FILLED 51 · FIXED 958). Remaining gaps are almost entirely `mini_set` / `fees_detail` shells with no Issue Date / inspection / close stamp in DATA.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Tamarac, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_tamarac.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_tamarac_repaired.parquet`

## DATA schema

| Family | n | Notes |
| --- | ---: | --- |
| `permit_status_*` | 1,628 | `detail` + `permit_status_detail` + inspection blocks |
| `fees_detail_*` | 215 | `detail` + fees only (no permit/inspection blocks) |
| `mini_set_*` | 157 | `application_status` / address / parcel only (no dates) |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `Status for Permit Number`, overridden by terminal `Application Status` (VOID / CANCELLED / NULL AND VOID / DUPLICATE); fees_detail / mini_set use `Application Status` alone |
| FILE_DATE | `Application Date` |
| PERMIT_DATE | `Issue Date` (not portal `Permit Date`) |
| FINAL_DATE | Later of successful FINAL/CO (else non-NOC) inspection and portal `Permit Date` when strictly after `Issue Date` |

## Field assessments

### STATUS_NORMALIZED

**399 missing** before repair — all `fees_detail` / `mini_set` shells where upstream only mapped `Status for Permit Number`.

Among populated rows, STATUS_NORMALIZED followed `STATUS_ORIGINAL` (`final inspection complete` / `closed` → Final, `permit printed` → Active, `plan check` / `to be issued` → In Review, `permit revoked` → Inactive) and ignored terminal `Application Status`. That produced **109** wrong labels, mainly:

- VOID / CANCELLED applications still labeled Final / Active / In Review from a stale CLOSED / PERMIT PRINTED / PLAN CHECK permit status
- A few C.O. / CERTIFICATE OF COMPLETION rows labeled Active instead of Final
- `TEMPORARY C.O. ISSUED` (1 row) unmapped upstream

**399 FILLED / 109 FIXED.** After: Final 1,524; Inactive 226; In Review 136; Active 114; **0 null**.

### FILE_DATE

Ideal: populated for all records.

- When both present (1,843 rows), FILE_DATE always equals `Application Date` (**0 FIXED**).
- **157 missing** are all `mini_set` shells with no date fields in DATA → **0 FILLED**.
- Coverage after repair: Active 100%; Final 91.0%; In Review 95.6%; Inactive 93.8%.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Upstream put portal **Permit Date** into PERMIT_DATE. On Final rows that stamp is usually a close/admin date *after* issuance (1,422 rows with Permit Date > Issue Date), so **1,493** of 1,522 comparisons vs Issue Date mismatched.
- **1,578 FIXED** (mostly Permit Date → Issue Date; 89 clears of unsupported stamps on In Review / no-Issue / fees_detail rows).
- **25 FILLED** where Issue Date existed but PERMIT_DATE was blank.
- Remaining Active/Final gap: **172** (137 mini_set + 19 fees_detail Final shells with no Issue Date; 16 Active permit_status rows with blank Issue Date).

Coverage after repair: Active 98/114 (86.0%); Final 1,368/1,524 (89.8%); In Review 0/136; Inactive 71/226 (issued-then-voided/cancelled). **0** PERMIT_DATE ≠ Issue Date among Active/Final/Inactive with Issue Date present. **0** FILE_DATE > PERMIT_DATE inversions.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream often used the latest successful inspection date, including NOC rows whose “completed” column is frequently exactly one year after the scheduled date (261 NOC pairs), producing late non-completion stamps.
- Repair prefers successful FINAL/CO inspections (excluding NOC fallback), then takes the later of that and post-issue Permit Date.
- **51 FILLED** / **958 FIXED** (948 value corrections + 10 clears when status remapped away from Final).
- Remaining Final gap: **156** — all mini_set / fees_detail shells with no inspections or Permit Date close stamp. Every `permit_status_*` Final has a FINAL_DATE.

Coverage after repair: Final 1,368/1,524 (89.8%); Active / In Review / Inactive 0%. **0** PERMIT_DATE > FINAL_DATE inversions.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 399 | 109 | 399 → 0 |
| FILE_DATE | 0 | 0 | 157 → 157 |
| PERMIT_DATE | 25 | 1,578 | 399 → 463 |
| FINAL_DATE | 51 | 958 | 673 → 632 |

PERMIT_DATE / FINAL_DATE missing counts rise slightly because unsupported stamps were cleared on In Review / Inactive / shell rows; coverage on Active and Final improves where Issue Date / inspection / close evidence exists.
