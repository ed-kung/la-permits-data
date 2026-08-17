# Tyler (TX) data repair

**Summary:** Tyler was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (2,000 rows). DATA is an eTrakit-style portal payload (`permit_info` / `permit_info_search_fallback`). STATUS_NORMALIZED is now fully populated (81 FILLED from blank/`TEMPORARY C.O. ISSUE`, 5 FIXED for stale FINALED/CO ISSUED/ISSUED). FILE_DATE is 100% via `search_data.APPLIED` on 80 blank-info rows. PERMIT_DATE gained 528 fills (Issued / search ISSUED / Approved). FINAL_DATE gained 8 fills and cleared 74 spurious non-Final finals. After repair, Active/Final PERMIT_DATE coverage is 98.8% / 98.7%; Final FINAL_DATE coverage is 77.5% (most CLOSED / CERTIFICATE ISSUED lack FinaledDate).

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through Carrollton; **Tyler** was the first missing pair → `agent/scripts/tx/data_repair_tx_tyler.py`.

## DATA schema

All 2,000 rows parse. Shared top-level keys: `contacts`, `fees`, `inspections`, `permit_info`, `search_data`, `site_info`.

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `permit_info` | 1,920 | Populated `PermitStatus` and usually dates |
| `permit_info_search_fallback` | 80 | Blank `permit_info` status/dates; usable `search_data` STATUS / APPLIED / ISSUED |

Canonical sources:

| Target | Primary | Fallback |
| --- | --- | --- |
| STATUS_NORMALIZED | `PermitStatus` | `search_data.STATUS`; else Finaled/Issued/Approved/Applied dates |
| FILE_DATE | `PermitAppliedDate` | `search_data.APPLIED`, then Issued / search ISSUED |
| PERMIT_DATE | `PermitIssuedDate` | `search_data.ISSUED`, then `PermitApprovedDate` |
| FINAL_DATE | `PermitFinaledDate` | latest approved FINAL / CO inspection `Completed` (Final only) |

## Field assessment

### STATUS_NORMALIZED

Before: Active 930 / Final 909 / missing 81 / Inactive 43 / In Review 37.

**Missing (81) — FILLED:**

| Source status | n | Mapping |
| --- | ---: | --- |
| (blank `permit_info`; `search_data.STATUS=ISSUED`) | 46 | Active |
| (blank; FINALED) | 10 | Final |
| (blank; FINAL INSP COMPLETE) | 9 | Final |
| (blank; PROJECTDOX / HOLD / UNDER REVIEW / RECEIVED / ETRAKIT APP) | 13 | In Review |
| (blank; APPROVED / VOID) | 1 + 1 | Active / Inactive |
| TEMPORARY C.O. ISSUE | 1 | Final |

Root cause for the 80 blank rows: recent eTrakit exports where `permit_info` date/status fields are empty strings while `search_data` still carries STATUS/APPLIED/ISSUED. Prior pipeline only read `PermitStatus` / `STATUS_ORIGINAL`, so status and all dates were left null.

**Incorrect (5) — FIXED:**

| PermitStatus | Prior → Correct | n | Cause |
| --- | --- | ---: | --- |
| FINALED | Active → Final | 2 | STATUS_ORIGINAL lagged as `issued` |
| CO ISSUED | Active → Final | 1 | same lag |
| ISSUED | In Review → Active | 2 | STATUS_ORIGINAL still `projectdox` after issuance |

After repair: Active 976 / Final 932 / In Review 48 / Inactive 44 / missing 0.

### FILE_DATE

- When present (1,920), always matched `PermitAppliedDate` at day resolution (1,897 with Applied; remainder already populated consistently).
- 80 missing — all `permit_info_search_fallback` — filled from `search_data.APPLIED`.
- After repair: 2,000 / 2,000 (100%).

### PERMIT_DATE

- When present (1,380), always matched Issued (or search ISSUED / Approved fallback) at day resolution; no wrong-date fixes.
- 528 FILLED: 463 from populated `permit_info` (mostly Approved-only Active/Final rows plus a few Issued), 65 from `search_data.ISSUED` on blank-info rows.
- Remaining gaps: 12 Active + 12 Final with neither Issued, search ISSUED, nor Approved in DATA (plus optional In Review / Inactive).

### FINAL_DATE

- Existing Final FINAL_DATE values matched `PermitFinaledDate` when both present (713 / 713); no wrong-date fixes among populated Final rows.
- 8 FILLED: 3 status-corrected Final rows with FinaledDate (2 FINALED + 1 CO ISSUED) plus 5 Final rows whose FinaledDate was blank but an approved FINAL / CO inspection `Completed` existed.
- 74 FIXED (cleared): 73 Active ISSUED rows that still carried `PermitFinaledDate` (often after a final inspection while portal status remained ISSUED) and 1 Inactive PERMIT REVOKED. Portal status is treated as authoritative; FINAL_DATE is only kept for Final.
- 210 Final rows remain without FinaledDate or FINAL/CO inspection dates — dominated by CLOSED (145) and CERTIFICATE ISSUED (22), plus blank-info FINALED / FINAL INSP COMPLETE (19) and some Complete (24).

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_tyler.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_tx_tyler_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 81 | 5 | 81 → 0 |
| FILE_DATE | 80 | 0 | 80 → 0 |
| PERMIT_DATE | 528 | 0 | 620 → 92 |
| FINAL_DATE | 8 | 74 | 1,212 → 1,278 |

(Missing FINAL_DATE rises because clearing 74 spurious non-Final dates outweighs the 8 fills.)

After repair by STATUS_NORMALIZED:

| Status | n | PERMIT_DATE | FINAL_DATE |
| --- | ---: | --- | --- |
| Active | 976 | 964 / 976 (98.8%) | 0 / 976 |
| Final | 932 | 920 / 932 (98.7%) | 722 / 932 (77.5%) |
| In Review | 48 | 7 / 48 (14.6%) | 0 / 48 |
| Inactive | 44 | 17 / 44 (38.6%) | 0 / 44 |

## Remaining gaps

- 24 Active/Final rows with no Issued, search ISSUED, or Approved date in DATA.
- 210 Final rows with no FinaledDate and no approved FINAL/CO inspection Completed date (especially CLOSED and CERTIFICATE ISSUED).
- Active ISSUED rows that look completed (FinaledDate + final inspection) are left Active per portal status; their FINAL_DATE values are cleared rather than promoting status to Final.
