# Pinecrest (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Pinecrest was first. Its DATA is the Accela / eTRAKiT family (`permit_info` + `search_data` + inspections), shared with Key West / Parkland. Upstream left **42** STATUS_NORMALIZED null (unmapped VERIFIED / ONLINE REWORKS / CC / blank archive shells) and mislabeled **8** rows from stale STATUS_ORIGINAL while PermitStatus was FINALED / EXPIRED / ACTIVE. FILE_DATE already matched PermitAppliedDate whenever present (**0** repairs; **805** historical shells have no application stamp). After repair: status nearly complete (FILLED 41 · FIXED 8 · 1 shell null); PERMIT_DATE filled from Issued/Approved (FILLED 25); FINAL_DATE filled from PermitFinaledDate or passed inspections (FILLED 506). Remaining gaps are almost entirely CONV/CNTY/CLOSED shells with blank Accela date fields.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Pinecrest, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_pinecrest.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_pinecrest_repaired.parquet`

## DATA schema

All 2,000 rows share top-level keys `fees`, `contacts`, `site_info`, `inspections`, `permit_info`, `search_data`. INFERRED_SCHEMA is content-based:

| Family | n | Notes |
| --- | ---: | --- |
| `accela_issued_finaled` | 838 | Issued + Finaled |
| `accela_issued` | 617 | Issued, no Finaled |
| `accela_applied` | 357 | Applied only |
| `accela_status_only` | 126 | Status, no dates |
| `accela_finaled` | 53 | Finaled, no Issued |
| `accela_approved` | 8 | Approved only |
| `accela_shell` | 1 | Empty status + dates |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `permit_info.PermitStatus` (+ Final when `PermitFinaledDate` set; blank+Issued → Active) |
| FILE_DATE | `PermitAppliedDate` (else `search_data.APPLIED`) |
| PERMIT_DATE | `PermitIssuedDate`, else `PermitApprovedDate` for Active/Final |
| FINAL_DATE | `PermitFinaledDate`, else latest passed final-ish / any passed inspection on/after Issued |

## Field assessments

### STATUS_NORMALIZED

**42 missing** before repair — unmapped portal codes: VERIFIED (10), ONLINE REWORKS (8+2 mismatched), blank archive CERT shells (20), CC (1), plus VOID/UNDER REVIEW rows whose STATUS_ORIGINAL disagreed with PermitStatus.

Among populated rows, STATUS_NORMALIZED mostly followed STATUS_ORIGINAL. **8 FIXED** where PermitStatus (or a Finaled stamp) disagreed:

- FINALED (+ Finaled date) still labeled Active / In Review from STATUS_ORIGINAL `active` / `under review` / `approved` (5)
- EXPIRED still labeled Active (2)
- ACTIVE still labeled In Review from STATUS_ORIGINAL `on hold` (1)

**41 FILLED / 8 FIXED.** After: Final 1,521; In Review 251; Inactive 175; Active 52; **1 null** (`PROC20102989` empty shell).

### FILE_DATE

Ideal: populated for all records.

- When both present (1,195 rows), FILE_DATE always equals `PermitAppliedDate` (**0 FIXED / 0 FILLED**).
- **805 missing** — mostly CONV/CNTY historical and CLOSED shells with blank Applied; Issued / fee / inspection dates are not treated as application dates.
- Coverage after repair: Active 59.6%; Final 53.0%; In Review 100%; Inactive 61.1%.
- **35** FILE_DATE > PERMIT_DATE pairs exist in Accela itself (Applied after Issued); present before repair and left as-is.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Upstream already copied `PermitIssuedDate` when present (**1,452** matches; **0 FIXED**).
- **25 FILLED**: 3 Issued blanks that had Issued in DATA but null PERMIT_DATE; 22 Approved-only Active/Final rows.
- Remaining Active/Final gap: **127** — FINALED/CLOSED/CC shells with neither Issued nor Approved (status_only / finaled / applied-only).

Coverage after repair: Active 47/52 (90.4%); Final 1,399/1,521 (92.0%); In Review 1/251 (ON HOLD with Issued kept); Inactive 30/175 (issued-then-voided/expired). **0** PERMIT_DATE ≠ Issued among Active/Final/Inactive with Issued present.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream used `PermitFinaledDate` when present (**886** matches; **0** value FIXED).
- **506 FILLED** from Finaled stamps on status-remapped rows and from passed inspections (`PASS` / `APPROVED` / `PARTIAL` / `VERIFIED`), preferring final-typed inspections and requiring Completed ≥ Issued when Issued exists (avoids bad pre-issue FINAL stamps).
- Remaining Final gap: **129** — CLOSED (41) and FINALED/CC shells with blank Finaled and no usable passed inspection.
- Non-Final rows carry **0** FINAL_DATE after repair.

Coverage after repair: Final 1,392/1,521 (91.5%); Active / In Review / Inactive 0%. **0** PERMIT_DATE > FINAL_DATE inversions.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 41 | 8 | 42 → 1 |
| FILE_DATE | 0 | 0 | 805 → 805 |
| PERMIT_DATE | 25 | 0 | 548 → 523 |
| FINAL_DATE | 506 | 0 | 1,114 → 608 |
