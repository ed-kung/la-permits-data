# Sanibel (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** Among Florida sample jurisdictions missing a repair script, Sanibel was first. Its DATA is a Tyler EnerGov payload (`entity` / `details` / optional `reviews` extras). STATUS_NORMALIZED was null on 34 rows (unmapped `Issued Dev Permit` / `Closed HB 447`) and wrong on 19 more (stale `STATUS_ORIGINAL` vs current `CaseStatus`) — all 53 were FILLED or FIXED. FILE_DATE already matched `ApplyDate` on every row. PERMIT_DATE gained 5 FILLED values after Issued Bldg Permit corrections and cleared 3 spurious In Review issuance stamps. FINAL_DATE gained 13 FILLED values on Active→Final upgrades and cleared 73 spurious non-Final finals (mostly Void/Canceled/Abandoned). Post-repair, every row matches EnerGov status/date sources with no residual mismatches; remaining Final FINAL_DATE gaps are Converted / Closed HB 447 / Closed/Complete shells with null `FinalDate`.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Sanibel, FL** (2,001 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_sanibel.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/repaired/permits_fl_sanibel_repaired.parquet`

## DATA schema

All rows share EnerGov top-level keys `contacts`, `details`, `entity`, `fees`, `processing_status`. 33 rows also carry `attachments` / `reviews` / `holds` / `more_info` (`energov_full_*`). Some `CaseStatus` values include a trailing space (`Converted `, `Issued Dev Permit `); the repair strips before mapping. Variants are classified by which canonical dates are populated:

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `energov_issued_finaled` | 1,711 | Issued + Finaled |
| `energov_issued` | 173 | Issued, no Finaled |
| `energov_finaled` | 54 | Finaled, no IssueDate |
| `energov_applied` | 30 | Apply only |
| `energov_full_applied` | 15 | full keyset, apply only |
| `energov_full_issued` | 15 | full keyset, issued |
| `energov_full_finaled` | 2 | full keyset, finaled |
| `energov_full_issued_finaled` | 1 | full keyset, issued + finaled |

Canonical mappings:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (fallback `details.PermitStatus`), stripped |
| FILE_DATE | `entity.ApplyDate` (fallback `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (fallback `details.IssueDate`) for Active/Final/Inactive |
| FINAL_DATE | `entity.FinalDate` (fallback `details.FinalizeDate`) for Final only |

CaseStatus → normalized: Certificate of Completion / Cerificate of Occupancy (agency typo) / Closed/Complete / Converted / Closed HB 447 → Final; Issued / Issued Bldg Permit / Issued Dev Permit → Active; In Review / Submitted - Online / Ready to Issue → In Review; Void / Canceled / Abandoned / Withdrawn / Expired / Denied → Inactive.

## Field assessments

### STATUS_NORMALIZED

**34 missing.** `Issued Dev Permit` (14) and `Closed HB 447` (20) were never mapped from `STATUS_ORIGINAL`.

**19 incorrect** from stale STATUS_ORIGINAL vs current EnerGov status:

- Certificate of Completion still labeled Active (13) — STATUS_ORIGINAL stayed `issued bldg permit` while `FinalDate` was already set
- Issued Bldg Permit still labeled In Review (5) — STATUS_ORIGINAL was `in review` / `ready to issue`
- Canceled still labeled In Review (1)

**34 FILLED / 19 FIXED.** Distribution: Final 1,723→1,756; Active 122→128; Inactive 73→74; In Review 49→43; null 34→0.

### FILE_DATE

Ideal: populated for all records.

- Before/after: **0 missing**. When both present (2,001 rows), FILE_DATE always equals `ApplyDate` (**0 FILLED / 0 FIXED**).
- Coverage after repair: 100% across all statuses.
- Note: 1 source row has ApplyDate one calendar day after IssueDate (left as-is).

### PERMIT_DATE

Ideal: populated for Active and Final.

- When IssueDate and PERMIT_DATE were both present, they always matched prior to status-driven clears (**0 value FIXED**).
- **5 FILLED**: Issued Bldg Permit rows upgraded from In Review that had IssueDate but blank PERMIT_DATE.
- **3 FIXED clears**: Ready to Issue / other In Review rows incorrectly carrying PERMIT_DATE (CaseStatus trusted over `details.Issued`).
- Remaining Active/Final gap: **30** = 27 Closed/Complete + 2 Converted + 1 Issued shell with null IssueDate / `Issued=False`. Not inventable from DATA.
- Remaining overall gap: **104**.

Coverage after repair: Active 127/128 (99.2%); Final 1,727/1,756 (98.3%); In Review 0/43; Inactive 43/74 (58.1%, issued-then-voided/canceled/abandoned).

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- **13 FILLED** on Active→Final upgrades (Certificate of Completion) that already had `FinalDate` / `FinalizeDate` but blank FINAL_DATE under the old Active label.
- **73 FIXED clears**: non-Final rows incorrectly carrying final/closeout stamps — Inactive Void/Canceled/Abandoned/Withdrawn/Denied/Expired (70), Active Issued shells (2), In Review Ready to Issue (1).
- Remaining Final gap: **62** = Converted (49) + Closed HB 447 (11) + Closed/Complete (2) with null `FinalDate` / `FinalizeDate`. No alternate final date in `processing_status` or other entity date fields.
- 10 legacy rows have IssueDate after FinalDate in the source JSON; left as-is.

Coverage after repair: Final 1,694/1,756 (96.5%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 34 | 19 | 34 → 0 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 5 | 3 | 106 → 104 |
| FINAL_DATE | 13 | 73 | 247 → 307 |

Residual mismatches vs EnerGov sources after repair: status 0, file 0, permit 0, final 0.
