# Homestead (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Homestead was first. Its DATA is a single flat portal schema (`apply_date` / `issue_date` / `permit_status` / `inspection_review`). FILE_DATE and PERMIT_DATE already matched the portal dates whenever present. The main defects were (1) 28 issued OPEN/HOLD rows labeled In Review instead of Active, and (2) all 1,728 Final rows missing FINAL_DATE. After repair: STATUS FIXED 28; FINAL_DATE FILLED 1,536 from PASSED inspections (clamped to `issue_date` when the portal recorded a pre-issuance inspection). Remaining gaps are blank `issue_date` ("-") shells—mostly CLOSED shop drawings / revisions with no PASSED inspection dates.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Homestead, FL** (2,000 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_homestead.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_homestead_repaired.parquet`

## DATA schema

All 2,000 rows share the same top-level keys. `INFERRED_SCHEMA` is `homestead_{status}_{date_profile}`:

| Schema family (top counts) | n | Notes |
| --- | ---: | --- |
| `homestead_closed_issued_finalable` | 1,536 | CLOSED + issue_date + PASSED insp date |
| `homestead_closed_applied` | 141 | CLOSED, `issue_date` = "-" |
| `homestead_voided_*` | 132 | VOIDED |
| `homestead_expired_*` | 81 | EXPIRED |
| `homestead_open_*` | 56 | OPEN (issued → Active after repair) |
| `homestead_hold_issued_finalable` | 2 | HOLD with issue_date → Active |
| `homestead_rejected_applied` | 1 | REJECTED |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `permit_status`; OPEN/HOLD with real `issue_date` → Active |
| FILE_DATE | `apply_date` |
| PERMIT_DATE | `issue_date` (sentinel "-" treated as missing) |
| FINAL_DATE | Latest PASSED FINAL*/CO inspection date, else latest PASSED inspection; clamped ≥ `issue_date` when both present |

## Field assessments

### STATUS_NORMALIZED

No missing values. Upstream mapped CLOSED→Final, EXPIRED/VOIDED/REJECTED→Inactive, OPEN/HOLD→In Review, and left **Active empty** (0 rows).

Incorrect: **28** OPEN (26) / HOLD (2) rows with a populated `issue_date` were In Review despite being issued. Remapped to **Active**. Remaining 30 OPEN rows have `issue_date` = "-" and correctly stay In Review.

**0 FILLED / 28 FIXED.** After: Final 1,728; Inactive 214; In Review 30; Active 28; **0 null**.

### FILE_DATE

Ideal: populated for all records.

- All 2,000 rows already match `apply_date` (**0 FILLED / 0 FIXED**).
- Coverage after repair: 100% for every status.

### PERMIT_DATE

Ideal: populated for Active and Final.

- When both present (1,701 rows), PERMIT_DATE always equals `issue_date` (**0 FIXED**).
- **299 missing** mirror blank `issue_date` ("-") — including **141 Final** CLOSED shells (mostly SHOP DRAWING / REVISION TO PERMIT / GARAGE/YARD SALE with empty or PENDING-only inspections). No alternate issuance stamp in DATA.
- After remapping issued OPEN/HOLD to Active, Active PERMIT_DATE coverage is **28/28 (100%)**. In Review carries **0** PERMIT_DATE (correct).

Coverage after repair: Active 28/28 (100%); Final 1,587/1,728 (91.8%); In Review 0/30; Inactive 86/214 (issued-then-voided/expired). **0** FILE_DATE > PERMIT_DATE inversions.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream left **every** FINAL_DATE null (2,000), including all Final rows — the portal has no top-level final/close date field.
- Repair fills from `inspection_review`: prefer PASSED inspections whose `inspection_header` contains FINAL / C.O / CERTIFICATE; else latest PASSED date (`Inspection Date`, fallback `Scheduled Date`).
- **1,536 FILLED** on Final rows. When the inspection date precedes `issue_date` (18 portal quirks), FINAL_DATE is clamped to `issue_date`.
- Remaining Final gap: **192** — CLOSED shells with no PASSED inspection date (152 empty `inspection_review`, rest PENDING-only / failed-only).

Coverage after repair: Final 1,536/1,728 (88.9%); Active / In Review / Inactive 0%. **0** PERMIT_DATE > FINAL_DATE inversions.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 28 | 0 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 0 | 299 → 299 |
| FINAL_DATE | 1,536 | 0 | 2,000 → 464 |

After repair, the 464 missing FINAL_DATE values are non-Final rows (should be null) plus 192 Final shells without usable inspection dates.
