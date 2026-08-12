# Citrus County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after West Palm Beach in list order) was **Citrus County**. DATA mixes a CityView-style detail payload (`Added On` / `Issued On` / `Final On`, often with `init_info.Status`) and a smaller legacy flat payload (`Date Created` / `Issued Date` / `Exp. Date`) with no status or final stamp. STATUS_NORMALIZED was filled on all 587 legacy rows and fixed on 97 CityView rows where list `STATUS_ORIGINAL=closed` disagreed with `init_info.Status` (or Final On). FILE_DATE was already complete and correct. PERMIT_DATE gained 678 fills from `Issued On`. FINAL_DATE gained 502 fills from `Final On` and cleared 593 incorrect values (mostly legacy `Exp. Date` copied into FINAL_DATE, plus FINAL_DATE on non-Final rows after status repair).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in file order. Existing FL repair scripts covered Jacksonville through West Palm Beach. **Citrus County** was the first without `agent/scripts/fl/data_repair_fl_citrus_county.py`.

Sample size: **2,002** records.

## DATA schemas

Two portal families, further split by which dates are populated:

| INFERRED_SCHEMA            | Count |
| -------------------------- | ----: |
| `cityview_issued_finaled`  | 1,139 |
| `legacy_issued`            |   572 |
| `cityview_issued`          |   265 |
| `legacy_applied`           |    15 |
| `cityview_applied`         |    10 |
| `cityview_finaled`         |     1 |

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | CityView `init_info.Status` (else `STATUS_ORIGINAL`); `Final On` → Final unless Void/Expired/Withdrawn. Legacy: Issued Date → Active, else In Review |
| FILE_DATE         | `Added On` / `Date Created`                                                 |
| PERMIT_DATE       | `Issued On` / `Issued Date`                                                 |
| FINAL_DATE        | `Final On` only (CityView Final rows). Legacy `Exp. Date` is not a final date |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,392 · missing 587 · Active 9 · In Review 7 · Inactive 7.

- All **587** legacy rows had null `STATUS_ORIGINAL` / `STATUS_NORMALIZED` (payload has no status field) → **FILLED** as Active (572 with Issued Date) or In Review (15 without).
- CityView list scrape often labeled records `closed` while detail `init_info.Status` said otherwise (Issued, Out To Applicant, Void, etc.) → **FIXED** using `init_info.Status`, with `Final On` forcing Final except for Void/Expired/Withdrawn.
- Notable fixes: 48 Issued→Active; 19 Out To Applicant→In Review; 10 Void(+Final On)→Inactive; 6 Closed (labeled issued/Active)→Final; plus smaller review/inactive corrections.

After: Final 1,313 · Active 624 · In Review 45 · Inactive 20 · missing 0.  
Flags: **FILLED 587 · FIXED 97**.

### FILE_DATE

Before: 0 missing. Ideal: populated for all records.

- Upstream FILE_DATE matched `Added On` / `Date Created` on every row (**0** day mismatches, **0** fills/fixes).
- Coverage remains **100%** for all statuses.

After: 0 missing.  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 704 missing. Ideal: populated for Active and Final.

- When present, PERMIT_DATE already matched `Issued On` / `Issued Date` (**0** mismatches).
- **678** CityView rows had `Issued On` but null PERMIT_DATE → **FILLED**.
- **26** rows still lack an issued stamp in DATA (11 CityView + 15 legacy applied-only) → not repairable.
- 47 rows have Issued On on a calendar day before Added On (amendment / conversion chronology); left as-is since Issued On is the correct PERMIT_DATE source.

After: 26 missing. Coverage: Active **100%**; Final **99.2%**.  
Flags: **FILLED 678 · FIXED 0**.

### FINAL_DATE

Before: 788 missing; many non-missing values on legacy rows were expiration dates. Ideal: populated for Final only.

- CityView: when present, FINAL_DATE already matched `Final On` (**0** mismatches). **502** Final rows with `Final On` but null FINAL_DATE → **FILLED**.
- Legacy: **578** FINAL_DATE values equaled `Exp. Date` (not a completion date) → **FIXED** (cleared). No true final field exists in legacy DATA.
- After status demotions (Issued/Out To Applicant/Void/etc. no longer Final), residual FINAL_DATE on non-Final rows → **FIXED** (cleared). **0** non-Final rows retain FINAL_DATE.
- **190** Final rows still lack `Final On` → FINAL_DATE stays missing. `Certified On` never appears when `Final On` is blank, so it is not a useful fallback here.

After: 879 missing (increase vs before is expected: wrong Exp. Date finals removed). Coverage: Final **85.5%**; Active/In Review/Inactive **0%**.  
Flags: **FILLED 502 · FIXED 593**.

## Repair script

- Script: `agent/scripts/fl/data_repair_fl_citrus_county.py`
- Entry point: `data_repair(df)`
- Artifact: `AGENT_DATA_PATH/citrus_county_repaired_sample.parquet`
