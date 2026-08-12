# North Miami (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, North Miami was first. Its DATA is a single Accela-style nested payload (`main` / `actions` / `routing`). The dominant defect is **817 rows with blank STATUS_NORMALIZED** because `main.Status` (and `STATUS_ORIGINAL`) are absent — almost all LEGACY BUILDING PERMITS that already carry Applied/Issued/Final dates. The repair FILLS 814 of those from the date pattern (801→Final, 12→Active, 1→In Review). FILE_DATE already matches `main.Applied` wherever both exist (3 empty shells remain). PERMIT_DATE gains 20 FILLED values (mainly Active `approved` from `main.Approved`, plus Inactive issued/expired). FINAL_DATE has 69 FIXED clears on non-Final rows that incorrectly retained `main.Final` (canceled / stop work). Post-repair: Active/Final/In Review/Inactive all have 100% FILE_DATE; Active 100% PERMIT_DATE; Final 100% FINAL_DATE; 389 Final rows still lack an issuance/approval stamp in DATA.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **North Miami, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_north_miami.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_north_miami_repaired.parquet`

## DATA schema

All 2,000 rows share the same top-level key set: `fees`, `main`, `parcel`, `actions`, `address`, `details`, `routing`, `valuation`, `conditions`, `contractors`, `description`, `permit_number`.

`main` holds the canonical fields (`Status`, `Applied`, `Issued`, `Approved`, `Final`, `Type`). **817 rows omit `Status`** (and use legacy address/description key names). Variants are labeled `accela_{status}_{date_suffix}`:

| INFERRED_SCHEMA (top) | n | Notes |
| --- | ---: | --- |
| `accela_none_issued_finaled` | 801 | No Status; Applied+Issued+Final (legacy) |
| `accela_final_issued_finaled` | 512 | Status=final with Issued |
| `accela_final_finaled` | 393 | Status=final, no Issued/Approved |
| `accela_issued_issued` | 98 | Status=issued |
| `accela_pending_applied` | 87 | Status=pending |
| `accela_canceled_finaled` | 56 | Status=canceled with Final stamp |
| `accela_shell` | 3 | Empty `main` (Building Property Search) |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `main.Status`; if absent, infer from Final → Final, Issued/Approved → Active, Applied only → In Review |
| FILE_DATE | `main.Applied` |
| PERMIT_DATE | `main.Issued`, else `main.Approved`, else completed issue action |
| FINAL_DATE | `main.Final`, else completed finalize-permit action (Final only) |

Status → normalized: `final`→Final; `issued`/`approved`→Active; `pending`/`stop work`→In Review; `canceled`/`expired`→Inactive.

## Field assessments

### STATUS_NORMALIZED

**817 missing** before repair. Among the 1,183 rows with `main.Status`, STATUS_NORMALIZED already matched the portal status exactly (**0 FIXED** among mapped statuses).

Root cause of missing values: legacy / early Accela exports omit `Status` and `STATUS_ORIGINAL`. Date patterns on `main` still encode lifecycle:

| Pattern (no Status) | n | Inferred |
| --- | ---: | --- |
| Applied + Issued + Final | 801 | Final |
| Applied + Issued (no Final) | 12 | Active |
| Applied only | 1 | In Review |
| Empty `main` shell | 3 | unrepairable |

**814 FILLED / 0 FIXED.** After: Final 905→1,706; Active 105→117; In Review 89→90; Inactive 84; missing 817→3.

### FILE_DATE

Ideal: populated for all records.

- Before: **3 missing** (the empty shells). When both present, FILE_DATE always equals `main.Applied` (**0 FIXED**, **0 FILLED**).
- Remaining gap: **3** shells with no Applied date in DATA.
- Coverage after repair: 100% for Active / Final / In Review / Inactive.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When both present, PERMIT_DATE always equals `main.Issued` (**0 date-value FIXED** against Issued).
- **20 FILLED**: 7 Active `approved` rows (Issued blank, Approved set), 4 Final rows with Approved only, plus Inactive issued/expired rows missing PERMIT_DATE.
- **2 FIXED**: In Review `stop work` rows incorrectly retaining issuance dates → cleared.
- Remaining Active/Final gap: **389 Final** rows (mostly REOCCUPANCY CERTIFICATE, MHVIO, NUISANCE PROHIBITED) with neither Issued nor Approved and no issue action → cannot invent from Final date.

Coverage after repair: Active 117/117 (100%); Final 1,317/1,706 (77.2%); In Review 0/90; Inactive 28/84.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- When both present on Final rows, FINAL_DATE always equals `main.Final` (**0 FILLED** needed for Final — already complete, including newly inferred Final legacy rows).
- **69 FIXED**: cleared FINAL_DATE on non-Final rows that carried `main.Final` (68 canceled Inactive + 1 stop work In Review). Those stamps behave as cancel/close dates, not permit finaling.
- Remaining gap: **0 Final** missing FINAL_DATE. Three shells stay without status/dates.

Coverage after repair: Final 1,706/1,706 (100%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 814 | 0 | 817 → 3 |
| FILE_DATE | 0 | 0 | 3 → 3 |
| PERMIT_DATE | 20 | 2 | 556 → 538 |
| FINAL_DATE | 0 | 69 | 225 → 294 |

Missing FINAL_DATE rises because incorrect non-Final finals were cleared. No FILE>PERMIT or PERMIT>FINAL day-level inversions after repair.

## Not repairable from DATA

- 3 empty Building Property Search shells (`accela_shell`)
- 389 Final records with no Issued/Approved/issue-action timestamp (code-enforcement / reoccupancy workflows that final without a separate issuance stamp)
