# Polk County (FL) data repair

**Summary:** First FL sample jurisdiction without an existing repair script (after Lakeland in file order) was **Polk County**. DATA is a single Accela Citizen Access family (`status` / `search_data` / `tasks` / `inspections`). STATUS_ORIGINAL is often stale relative to live `DATA.status`; remapping filled 38 nulls and fixed 122 labels (mostly Active→Final when the portal already said Closed-Complete). FILE_DATE was already complete and matched `search_data.Date` on all rows. PERMIT_DATE gained 32 fills and 94 fixes from Ready to Issue `Issued` (many prior values incorrectly equaled Cert Occupancy Issued). FINAL_DATE was the largest win: **283 FILLED** and **219 date FIXED** (plus 15 non-Final clears), lifting Final coverage from 75.2% to **89.3%**. After repair: STATUS fully populated; FILE_DATE 100%; Active PERMIT_DATE 96.4%; Final PERMIT_DATE 51.8%; Final FINAL_DATE 89.3%; non-Final FINAL_DATE 0.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_fl_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in file order. Existing FL repair scripts covered Jacksonville through Lakeland. **Polk County** was the first without `agent/scripts/fl/data_repair_fl_polk_county.py`.

Sample size: **1,999** records.

## DATA schemas

| INFERRED_SCHEMA | Count |
| --------------- | ----: |
| `accela_full`   | 1,519 |
| `accela_basic`  |   472 |
| `accela_shell`  |     8 |

Canonical source fields:

| Target field      | DATA source                                                                 |
| ----------------- | --------------------------------------------------------------------------- |
| STATUS_NORMALIZED | `DATA.status` (else `search_data.Status`)                                   |
| FILE_DATE         | `search_data.Date` else `DATA.date` else earliest Application Submittal     |
| PERMIT_DATE       | Earliest Ready to Issue task marked `Issued`                                |
| FINAL_DATE        | Certificate Issuance (CO/CC Issued, else Cert Not Required); else Inspections `Complete`; else passed FINAL inspection; else `more_details` Certificate of Occupancy |

## Field assessments

### STATUS_NORMALIZED

Before: Final 1,516 · Active 197 · Inactive 163 · In Review 85 · missing 38.

- Upstream mapping used `STATUS_ORIGINAL`, which disagrees with live `DATA.status` on **142** rows (e.g. ORIGINAL=`inspections` while DATA=`Closed-Complete`).
- **38 FILLED** nulls from unmapped originals (`closed-inactive`, `active permit`, `closure verification`, `waiting for revisions`, `closed-permits required`, etc.).
- **122 FIXED**, mainly:
  - Active → Final when DATA is `Closed-Complete` / `Closed-CO Issued` (72)
  - In Review → Active when DATA is `Inspections` (13)
  - In Review → Final for complete/closed portal statuses (20)
  - Active → Inactive for `Expired` (7)

After: Final 1,620 · Inactive 184 · Active 140 · In Review 55 · missing 0.  
Flags: **FILLED 38 · FIXED 122**.

### FILE_DATE

Before: 0 missing. Ideal: populated for all records.

- FILE_DATE already matched `search_data.Date` on **1,999 / 1,999** rows (0 day mismatches).
- No fills or fixes required.

After: 0 missing (100%).  
Flags: **FILLED 0 · FIXED 0**.

### PERMIT_DATE

Before: 999 missing. Ideal: populated for Active and Final.

- Canonical issuance signal is Ready to Issue marked `Issued` (present on 1,024 rows).
- **94 FIXED**: prior PERMIT_DATE often equaled Certificate Issuance `Cert Occupancy Issued` (a finalization date), not the issuance date.
- **32 FILLED** on Active/Final rows that had an Issued event but a null PERMIT_DATE.
- **781** Final rows still lack PERMIT_DATE — almost all have empty Ready to Issue event lists (legacy / conversion shells spanning ~2010–2025). Not repairable from DATA.

After: 967 missing. Coverage: Active **96.4%** (135/140); Final **51.8%** (839/1,620).  
Flags: **FILLED 32 · FIXED 94**.

### FINAL_DATE

Before: 821 missing; Final coverage 1,140/1,516 (75.2%). Ideal: populated for Final.

- Many populated FINAL_DATE values matched Inspections `Complete` but lagged Certificate Issuance closeout.
- **283 FILLED** on Final rows, primarily from `Cert Not Required` (trade permits) and certificate / inspection closeout.
- **219 FIXED** date corrections (all moved later, onto CO/CC Issued or equivalent closeout).
- **15 FIXED** clears of spurious FINAL_DATE on non-Final rows after status remap.
- **174** Final rows still lack FINAL_DATE — no certificate event, Inspections Complete, passed FINAL inspection, or `more_details` CO date.

After: 553 missing. Final coverage **89.3%** (1,446/1,620). Non-Final FINAL_DATE: **0**.  
Flags: **FILLED 283 · FIXED 234**.

## Artifacts

- Repair script: `agent/scripts/fl/data_repair_fl_polk_county.py` (`data_repair`)
- Repaired sample: `AGENT_DATA_PATH/polk_county_repaired_sample.parquet`
