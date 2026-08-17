# Carrollton (TX) data repair

**Summary:** Carrollton was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows). DATA is an Accela/CitizenAccess-style payload (`permits` / `permits_project` / `permit_info`) sharing a `Summary` block. STATUS_NORMALIZED had 2 missing values and 11 stale mappings vs `Application Status`. FILE_DATE was already complete and correct. PERMIT_DATE gained 6 fills from `Issued Date`. FINAL_DATE gained 5 fills from usable `Date Finaled` values and cleared 41 spurious values on non-Final rows. After repair, Active/Final PERMIT_DATE coverage is 100% / 99.8%; Final FINAL_DATE coverage remains low at 22.4% because most Closed rows omit `Date Finaled` (and 29 Closed rows only have 2090–2099 sentinel finaled dates).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through McKinney; **Carrollton** was the first missing pair → `agent/scripts/tx/data_repair_tx_carrollton.py`.

## DATA schema

All 2,000 rows parse. Three content variants (same `Summary` repair fields):

| Schema | n | Top-level keys |
| --- | ---: | --- |
| `permits` | 1,459 | Locations? + Permits + Summary |
| `permit_info` | 480 | Locations? + Permit Info + Summary |
| `permits_project` | 61 | permits + `project_id` |

Canonical sources:

- `Summary.Application Status` → STATUS_NORMALIZED
- `Summary.Application Date` → FILE_DATE
- `Summary.Issued Date` → PERMIT_DATE
- `Summary.Date Finaled` → FINAL_DATE (Final only; years outside 1900–2035 rejected as sentinel)

`Permit Status` on the Permits list / Permit Info dict often lags or conflicts with `Application Status` (e.g. Closed with Permit Status Expired / In Plan Check). Application Status is treated as authoritative to match the dominant existing normalization.

## Field assessment

### STATUS_NORMALIZED

Before: Final 1,641 / Active 279 / Inactive 59 / In Review 19 / missing 2.

Issues:

1. **Missing (2):** STATUS_ORIGINAL=`returned for correction` (Application Status Returned for Correction → In Review) and `invalid license` on a Closed case with Date Finaled → Final.
2. **Stale vs Application Status (11):** STATUS_ORIGINAL lagged portal Application Status — Closed still coded as permit(s) issued (3) / ready for issuance (1) / pending (1) / in plan check (1); Expired still permit(s) issued (3); Permit(s) Issued still pending (1) / in plan check (1).

Repair map (Application Status → normalized): Closed → Final; Permit(s) Issued → Active; Ready for Issuance / In Plan Check / On Hold / Returned for Correction → In Review; Expired / Withdrawn / Denied / Canceled / Closed - Incomplete Submittal → Inactive.

### FILE_DATE

Already 2,000 / 2,000 populated; all match `Application Date` at day resolution. No fills or fixes.

### PERMIT_DATE

When both present, PERMIT_DATE always matches `Issued Date` (1,947 / 1,947). Six rows had Issued Date but missing PERMIT_DATE (stale In Review / missing-status rows that were actually Closed or Permit(s) Issued). After repair, only 4 Final rows lack PERMIT_DATE — all have no `Issued Date` key in Summary.

### FINAL_DATE

- Existing Final FINAL_DATE values match Date Finaled when both exist (405 / 405); no wrong-date fixes among populated Final rows.
- 5 Closed rows with a usable Date Finaled lacked FINAL_DATE → FILLED (includes status-corrected Closed rows).
- 29 Closed rows carry Date Finaled in 2090–2099 (portal sentinel); these are not written into FINAL_DATE.
- 41 non-Final rows carried spurious FINAL_DATE (39 Active Permit(s) Issued, often older Expired Permit Status cases with a historical Date Finaled; 2 Inactive) → cleared.
- 1,250 Closed rows have no Date Finaled at all despite Permit Status often Finaled; no alternate completion timestamp exists in DATA.

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_carrollton.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_tx_carrollton_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 2 | 11 | 2 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 6 | 0 | 53 → 47 |
| FINAL_DATE | 5 | 41 | 1,595 → 1,631 |

(Missing FINAL_DATE rises after repair because clearing 41 spurious non-Final dates outweighs the 5 fills.)

After repair by STATUS_NORMALIZED:

| Status | n | PERMIT_DATE | FINAL_DATE |
| --- | ---: | --- | --- |
| Active | 275 | 275 / 275 (100.0%) | 0 / 275 |
| Final | 1,648 | 1,644 / 1,648 (99.8%) | 369 / 1,648 (22.4%) |
| In Review | 15 | 3 / 15 (20.0%) | 0 / 15 |
| Inactive | 62 | 31 / 62 (50.0%) | 0 / 62 |

## Remaining gaps

- **PERMIT_DATE:** 4 Final rows with no `Issued Date` in DATA.
- **FINAL_DATE:** 1,279 Final rows still missing — 1,250 omit Date Finaled entirely; 29 only have 209x sentinel values. Permit Status Finaled without Date Finaled is not a usable completion date.
