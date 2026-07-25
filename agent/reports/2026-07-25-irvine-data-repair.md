# Irvine data repair

**Summary:** First CA-sample jurisdiction without an existing repair script was Irvine (2,000 rows). DATA is a uniform Accela-style payload keyed on `main` (`main` ×1,980, `main_empty` ×20). Main defects: `STATUS_ORIGINAL` lagged behind `main.Status` on 16 rows; 2 finals with blank status/dates; 5 Active `approved` rows missing `PERMIT_DATE` (fillable from `Approved`); 14 rows remapped or filled to Final that needed `FINAL_DATE` from `main.Final`; 27 canceled/expired Inactive rows carrying spurious `FINAL_DATE`. `FILE_DATE` already matched `main.Applied` wherever both existed. Script: `agent/scripts/ca/data_repair_ca_irvine.py`. Artifact: `$AGENT_DATA_PATH/irvine_repaired_sample.parquet`.

## Sample and schemas

| INFERRED_SCHEMA | n |
| --- | ---: |
| main | 1,980 |
| main_empty | 20 |

Useful fields under `main`: `Status`, `Applied`, `Issued`, `Approved`, `Final`. `Expires` is a validity window, not a completion date. `main_empty` shells retain only address / description / permit_number.

Canonical mapping: `Status` → `STATUS_NORMALIZED`, `Applied` → `FILE_DATE`, `Issued` (else `Approved`) → `PERMIT_DATE`, `Final` → `FINAL_DATE`.

Status map: `final`→Final, `issued`/`approved`→Active, `pending`→In Review, `expired`/`canceled`→Inactive.

## STATUS_NORMALIZED

Upstream normalization followed `STATUS_ORIGINAL`, which usually equals `main.Status` but is stale on 16 rows (DATA advanced; original did not).

| Issue | Action |
| --- | --- |
| 2 `final` with null NORM | FILLED → Final |
| 8 `final` labeled Active (`issued`) | FIXED → Final |
| 4 `final` labeled In Review (`pending`) | FIXED → Final |
| 3 `issued` labeled In Review (`pending`) | FIXED → Active |
| 1 `canceled` labeled Active (`issued`) | FIXED → Inactive |

**Repair:** FILLED 2, FIXED 16. Missing 20 → 18.

After repair: Final 1,576, In Review 163, Inactive 129, Active 114, null 18.

Remaining nulls: 17 `main_empty` shells with no Status in DATA, plus 1 Encroachment Permit with blank `Status` (only Applied / Expires).

## FILE_DATE

Already populated and matched `main.Applied` at calendar-day resolution for 1,978 / 1,978 overlapping rows.

| Repair | n | Source |
| --- | ---: | --- |
| FILLED | 2 | `final` rows with Applied but missing FILE_DATE |
| FIXED | 0 | — |

Missing 19 → 17 (all `main_empty` with no Applied). Coverage after repair: 1,983 / 2,000 (99.2%). Three `main_empty` Final rows already had FILE_DATE from upstream with nothing in DATA to verify.

## PERMIT_DATE

Ideal: present for Active and Final. Where both `PERMIT_DATE` and `Issued` exist they always match (1,771 / 1,771).

| Repair | n | Source |
| --- | ---: | --- |
| FILLED | 14 | Issued on remapped Active/Final (9) + Approved on `approved` Active (5) |
| FIXED | 0 | — |

Coverage after repair: Active 114/114 (100%), Final 1,575/1,576 (99.9%).

Remaining Final without `PERMIT_DATE`: 1 fire-sprinkler case (`final`, Applied + Final present, blank Issued / Approved).

## FINAL_DATE

Ideal: present for Final. Existing Finals always matched `main.Final` when present.

| Repair | n |
| --- | ---: |
| FILLED | 14 |
| FIXED (cleared on non-Final) | 27 |

Fills: remapped / filled Finals that already had `main.Final` but no `FINAL_DATE`. Clears: canceled ×26 and expired ×1 Inactive rows whose `main.Final` is not a permit sign-off under the Active/Final/In Review/Inactive contract.

Coverage after repair: Final 1,576/1,576 (100%); Active / In Review / Inactive all 0%.

Missing `FINAL_DATE` rises (411 → 424) because clears outweigh fills.

## Performance summary

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 2 | 16 | 20 → 18 |
| FILE_DATE | 2 | 0 | 19 → 17 |
| PERMIT_DATE | 14 | 0 | 226 → 212 |
| FINAL_DATE | 14 | 27 | 411 → 424 |

## Why remaining gaps persist

1. **Empty `main` shells.** Seventeen records have no Status or dates in DATA — only address / description / permit number — so nothing to fill.
2. **Blank Status.** One Encroachment Permit has Applied / Expires but empty Status, Issued, Approved, and Final.
3. **Final without issuance.** One Final fire-sprinkler permit has Applied and Final but never recorded Issued or Approved.
4. **Expires is not Final.** Expiration dates must not populate `FINAL_DATE`.
