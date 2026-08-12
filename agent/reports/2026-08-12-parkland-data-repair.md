# Parkland (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Parkland was first. Its DATA is a single Accela-style nested payload (`permit_info` / `inspections` / `search_data`). STATUS_NORMALIZED was wrong on 18 rows because it followed a stale `STATUS_ORIGINAL` while `permit_info.PermitStatus` (or an existing `PermitFinaledDate`) already indicated Final/Inactive — all 18 were FIXED. FILE_DATE already matched `PermitAppliedDate` wherever both existed; 16 blanks remain with no application timestamp in DATA. PERMIT_DATE gained 13 FILLED values from `PermitApprovedDate` (or previously unused Issued on status-upgraded rows). FINAL_DATE gained 16 FILLED values after Active/In Review→Final upgrades. Post-repair, every row matches the Accela date/status sources with no residual mismatches.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Parkland, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_parkland.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/parkland_repaired_sample.parquet`

## DATA schema

All 2,000 rows share the same top-level key set: `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Variants are classified by which `permit_info` dates are populated:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `accela_issued_finaled` | 1,654 | Issued + Finaled present |
| `accela_applied` | 183 | Applied only |
| `accela_finaled` | 85 | Finaled, no Issued |
| `accela_issued` | 54 | Issued, no Finaled |
| `accela_status_only` | 13 | Status, no dates |
| `accela_approved` | 11 | Approved only |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus`; override to Final when `PermitFinaledDate` is set |
| FILE_DATE | `PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` (Active/Final) |
| FINAL_DATE | `PermitFinaledDate`, else latest approved final-ish inspection, else latest approved inspection (Final only) |

PermitStatus → normalized: FINALED / CO''ED → Final; ISSUED / APPROVED → Active; APPLIED → In Review; CANCELLED / VOID / VOIDED → Inactive.

## Field assessments

### STATUS_NORMALIZED

**0 missing.** Cross-tab of `PermitStatus` vs STATUS_NORMALIZED showed **17 direct mismatches**, plus **1** ISSUED row that already carried `PermitFinaledDate` (should be Final). Root cause: STATUS_NORMALIZED was derived from `STATUS_ORIGINAL` (e.g. `issued`, `applied`) that is out of sync with the current Accela `PermitStatus` (FINALED / CANCELLED).

**0 FILLED / 18 FIXED.** Distribution: Final 1,724→1,741; Inactive 219→220; Active 41→26; In Review 16→13.

### FILE_DATE

Ideal: populated for all records.

- Before: **16 missing**. When both present (1,984 rows), FILE_DATE always equals `PermitAppliedDate` (**0 FIXED**).
- All 16 missing rows also have blank `PermitAppliedDate`. A few have Issued/Approved or inspection dates, but those are not application/submittal dates → left missing (**0 FILLED**).
- Remaining gap: **16** (mostly Inactive VOID/VOIDED/CANCELLED shells, plus 2 Final, 2 In Review, 1 Active).

Coverage after repair: Active 96.2%; Final 99.9%; In Review 84.6%; Inactive 95.0%.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When both present, PERMIT_DATE always equals `PermitIssuedDate` (**0 FIXED**).
- **13 FILLED**: primarily Active/Final rows with blank Issued but populated `PermitApprovedDate`, plus 2 status-upgraded Final rows that had Issued available.
- Remaining Active/Final gap: **2 Active + 81 Final** with neither Issued nor Approved in DATA (cannot invent from Finaled).

Coverage after repair: Active 24/26 (92.3%); Final 1,660/1,741 (95.3%); In Review 0/13; Inactive 35/220 (issued-then-cancelled/voided).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- When both present, FINAL_DATE always equals `PermitFinaledDate` (**0 FIXED** against that source).
- **16 FILLED** on rows upgraded to Final that already had `PermitFinaledDate` but blank FINAL_DATE under the old Active/In Review label.
- One Active ISSUED row that incorrectly carried FINAL_DATE was upgraded to Final (finaled date override), so the date was retained rather than cleared.
- Remaining gap: **2 Final** rows with blank `PermitFinaledDate` and empty inspection lists.

Coverage after repair: Final 1,739/1,741 (99.9%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 18 | 0 → 0 |
| FILE_DATE | 0 | 0 | 16 → 16 |
| PERMIT_DATE | 13 | 0 | 294 → 281 |
| FINAL_DATE | 16 | 0 | 277 → 261 |

Post-repair validation against DATA: 0 status mismatches; 0 FILE/PERMIT/FINAL mismatches vs Accela sources; 0 Active/Final rows still missing PERMIT when Issued or Approved exists; 2 Final rows still missing FINAL_DATE (no source in DATA).
