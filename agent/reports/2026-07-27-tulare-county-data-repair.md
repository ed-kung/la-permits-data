# Tulare County (CA) data repair

**Summary:** Tulare County was the first `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing repair script. All 2,000 sample rows are Tyler EnerGov payloads (`entity` + `details`). Status had 17 nulls (`Incomplete/Resubmit`) and 58 stale mappings (mostly Active rows that already had `FinalDate`, plus a few Issued/Ready To Issue mismatches). `FILE_DATE` was already perfect. Four Active `PERMIT_DATE` gaps were fillable from `IssueDate`; ~162 Final rows still lack issuance dates in DATA. Spurious `FINAL_DATE` on non-Final rows was cleared; after repair, Final coverage is 99.9%.

## Jurisdiction selection

Went down first-seen `(JURISDICTION, STATE)` pairs in `MY_DATA_PATH/processed_data/permits_ca_sample.parquet`. Existing scripts live under `agent/scripts/{state}/data_repair_{state}_{city}.py`. First missing pair: **Tulare County, CA** (`agent/scripts/ca/data_repair_ca_tulare_county.py`).

## DATA schema

Two EnerGov key-set variants (same entity/details content):

| INFERRED_SCHEMA | n | Extra keys |
| --- | ---: | --- |
| `entity_fees` | 1,891 | — |
| `entity_fees_reviews` | 109 | `reviews`, `holds`, `attachments`, `more_info` |

Canonical sources:

| Field | Source |
| --- | --- |
| STATUS_NORMALIZED | `entity.CaseStatus` (else `details.PermitStatus`); Active + `FinalDate` → Final |
| FILE_DATE | `entity.ApplyDate` (else `details.ApplyDate`) |
| PERMIT_DATE | `entity.IssueDate` (else `details.IssueDate`) |
| FINAL_DATE | `entity.FinalDate` (else `details.FinalizeDate`) |

`CaseStatus` and `PermitStatus` always agree in this sample. `details.Issued` is a boolean, not a date.

## Field assessment

### STATUS_NORMALIZED

Pre-repair: Final 1,127 / Active 661 / In Review 110 / Inactive 85 / missing 17.

`STATUS_ORIGINAL` is generally a lowercased CaseStatus, but DATA is occasionally newer than the original scrape:

1. **17 `Incomplete/Resubmit`** with null `STATUS_NORMALIZED` → FILLED as **In Review**.
2. **52 Active rows with `FinalDate`** (41 Issued, 4 Finaled, 3 Approved, 3 Active, 1 Complete) → FIXED to **Final**. Root cause: status was taken from a stale Issued/Active label while EnerGov already recorded finalization (or CaseStatus itself moved to Finaled/Complete).
3. **3 Issued rows labeled In Review** (STATUS_ORIGINAL `ready to issue`) → FIXED to **Active**.
4. **2 Complete rows labeled In Review** (STATUS_ORIGINAL `applied`) → FIXED to **Final**.
5. **1 Ready To Issue labeled Active** (STATUS_ORIGINAL `approved`) → FIXED to **In Review**.

### FILE_DATE

0 missing. Every row’s `FILE_DATE` equals `entity.ApplyDate` (and `details.ApplyDate`). No repairs.

### PERMIT_DATE

When present, always equals `IssueDate` (0 mismatches). Ideal: populate for Active and Final.

Gaps before repair: 15 Active, 159 Final. Only **1 Active** (plus **3** that become Active after status fixes) had a fillable `IssueDate`. The 159 Final gaps are almost all `Complete`/`Finaled` cases with null `IssueDate` in DATA — not fillable.

### FINAL_DATE

When present, always equals `FinalDate`. Ideal: populate for Final only.

- **1 Final** row missing `FINAL_DATE` with empty FinalDate (I1500027) — not fillable.
- **7** Active→Final promotions had FinalDate in DATA but null `FINAL_DATE` → FILLED.
- **23** non-Final rows carried a `FINAL_DATE` (17 Incomplete/Resubmit, 2 In Review, 4 Inactive). EnerGov stores FinalDate on these statuses as a status-change stamp, not a true finalization → cleared (FIXED).

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_tulare_county.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/permits_ca_tulare_county_repaired.parquet`

| Field | FILLED | FIXED | Missing before | Missing after |
| --- | ---: | ---: | ---: | ---: |
| STATUS_NORMALIZED | 17 | 58 | 17 | 0 |
| FILE_DATE | 0 | 0 | 0 | 0 |
| PERMIT_DATE | 4 | 0 | 349 | 345 |
| FINAL_DATE | 7 | 23 | 804 | 820 |

Status after repair: Final 1,181 / Active 611 / In Review 123 / Inactive 85 (no nulls).

Coverage after repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 599/611 (98.0%); Final 1,019/1,181 (86.3%)
- FINAL_DATE: Final 1,180/1,181 (99.9%); 0 on non-Final

(`FINAL_DATE` missing count rises because clearing incorrect non-Final dates outweighs the 7 fills.)

## Remaining gaps (not repairable from DATA)

- **PERMIT_DATE:** 12 Active (Approved/Active/Ready To Issue with null IssueDate) and 162 Final (mostly Complete/Finaled with null IssueDate).
- **FINAL_DATE:** 1 Finaled row (I1500027) with no FinalDate/FinalizeDate.
