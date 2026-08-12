# Key West (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Key West was first. Its DATA is a single Accela / eTRAKiT-style nested payload (`permit_info` / `inspections` / `search_data`), the same family as Parkland. Upstream left **212** STATUS_NORMALIZED null (unmapped portal statuses, mainly `ADMCLOSE NO FIN INSP`) and **4** READY FOR PICKUP rows labeled In Review despite an issued date. FILE_DATE was already complete and correct. After repair: status complete (FILLED 212 · FIXED 4); PERMIT_DATE gained 17 FILLED from `PermitApprovedDate` where Issued was blank; FINAL_DATE gained 40 FILLED from approved inspections on CERTIFICATE ISSUED / COMPLETED / CLOSED rows. Remaining Active/Final PERMIT and Final FINAL gaps are almost entirely rows with blank Issued/Approved/Finaled and (for admin-close-no-final-insp) no usable final stamp in DATA.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Key West, FL** (1,999 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_key_west.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_key_west_repaired.parquet`

## DATA schema

All 1,999 rows share the same top-level key set: `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. Variants are classified by which `permit_info` dates are populated:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `accela_finaled` | 1,168 | Finaled, no Issued |
| `accela_issued` | 496 | Issued, no Finaled |
| `accela_issued_finaled` | 238 | Issued + Finaled |
| `accela_applied` | 83 | Applied only |
| `accela_approved` | 14 | Approved only |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus`; override to Final when `PermitFinaledDate` is set |
| FILE_DATE | `PermitAppliedDate` |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` (Active/Final) |
| FINAL_DATE | `PermitFinaledDate`, else latest approved final-ish inspection, else latest approved inspection (Final only; admin-close-no-final-insp statuses use Finaled only) |

PermitStatus → normalized (high level): FINALED / COMPLETED / CLOSED / CERTIFICATE ISSUED / CO / ADMCLOSE·ADM CLOSED NO FIN INSP → Final; PERMIT ISSUED / PERMIT PRINTED / APPROVED / READY FOR PICKUP → Active; application / information-required / review / waiting → In Review; CANCELLED / VOID / WITHDRAWN / DENIED / REJECTED / expired → Inactive.

## Field assessments

### STATUS_NORMALIZED

**212 missing** before repair — unmapped `PermitStatus` values that upstream never normalized:

| PermitStatus | n | Expected |
| --- | ---: | --- |
| ADMCLOSE NO FIN INSP | 175 | Final (twin of already-mapped ADM CLOSED NO FIN INSP) |
| INFORMATION REQUIRED | 11 | In Review |
| PERMIT EXPIRED / EXTENDED | 9 | Inactive |
| PERMIT APPLICATION | 5 | In Review |
| SENT BACK TO APPLICANT | 4 | In Review |
| EXPIRED: NO INSPECTIONS | 2 | Inactive |
| REVIEW / WAITING * | 6 | In Review |

Among populated rows, STATUS_NORMALIZED matched `PermitStatus` except **4** READY FOR PICKUP rows labeled In Review while `PermitIssuedDate` was set (should be Active, same family as PERMIT ISSUED / PERMIT PRINTED).

**212 FILLED / 4 FIXED.** After: Final 1,744; Active 189; Inactive 39; In Review 27; **0 null**.

### FILE_DATE

Ideal: populated for all records.

- Before: **0 missing**. When both present (1,999 rows), FILE_DATE always equals `PermitAppliedDate` (**0 FIXED / 0 FILLED**).
- Coverage after repair: **100%** for every STATUS_NORMALIZED class.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When both present (734 rows), PERMIT_DATE always equals `PermitIssuedDate` (**0 FIXED**).
- **17 FILLED**: Active/Final rows with blank Issued but populated `PermitApprovedDate`.
- Remaining Active/Final gap: **1,203** — almost all Final rows in the Accela pattern where Issued and Approved are blank (especially `accela_finaled` FINALED shells). One Active PERMIT PRINTED tree permit has neither Issued nor Approved.
- Two In Review INFORMATION REQUIRED rows retain PERMIT_DATE because Issued is present in DATA (not cleared).

Coverage after repair: Active 188/189 (99.5%); Final 542/1,744 (31.1%); In Review 2/27; Inactive 19/39 (issued-then-expired/cancelled). **0** PERMIT_DATE ≠ Issued among Active/Final/Inactive with Issued present. **0** FILE_DATE > PERMIT_DATE inversions.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- When both present (1,406 rows), FINAL_DATE always equals `PermitFinaledDate` (**0 FIXED** against that source).
- **40 FILLED** from approved inspections where Finaled was blank: CERTIFICATE ISSUED 29, COMPLETED 8, CLOSED 3.
- Admin-close-no-final-insp (`ADMCLOSE` / `ADM CLOSED NO FIN INSP`) intentionally skip inspection fallback — status text denies a final inspection — so only an explicit `PermitFinaledDate` populates FINAL_DATE (3 ADMCLOSE rows already had Finaled and kept it after status fill).
- Remaining Final gap: **298** (172 ADMCLOSE + 101 ADM CLOSED + 20 CLOSED + 5 COMPLETED) with blank Finaled and no usable inspection stamp under the rules above.
- Non-Final FINAL_DATE: **0** after repair (the 3 pre-repair ADMCLOSE rows with FINAL_DATE were filled to Final).

Coverage after repair: Final 1,446/1,744 (82.9%); Active / In Review / Inactive 0%. **2** PERMIT_DATE > FINAL_DATE inversions remain — both COMPLETED rows where Accela `PermitFinaledDate` precedes `PermitIssuedDate` (agency data quirk; values match DATA).

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 212 | 4 | 212 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 17 | 0 | 1,265 → 1,248 |
| FINAL_DATE | 40 | 0 | 593 → 553 |

Post-repair validation against DATA: 0 status nulls; 0 FILE/PERMIT/FINAL mismatches vs Accela Issued/Applied/Finaled sources; 17 Active/Final PERMIT fills from Approved; 40 Final FINAL fills from inspections; remaining PERMIT/FINAL gaps lack Issued/Approved/Finaled (and, for admin-close, lack a Finaled stamp by design).
