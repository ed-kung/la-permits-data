# Stuart (FL) data repair — STATUS_NORMALIZED and date fields

**Summary:** First FL sample jurisdiction without an existing repair script was **Stuart** (2,001 rows). DATA splits into CitizenServe (`main`/`extra`/`location`, 1,866) and a legacy `permit_info` extract (135). STATUS_NORMALIZED was already correct for CitizenServe; **2** legacy `Open` rows were FIXED from In Review → Active. FILE_DATE was already correct when present (**70** False Alarm / Contractor Registration shells remain unfillable). The main gaps were dates: **1,289** PERMIT_DATE fills (building + BTR issuance ASI / named HIST fields) and **801** FINAL_DATE fills (CO ASI + CE resolution + 12 legacy Passed final inspections). After repair, Final rows have PERMIT_DATE on 78.6% and FINAL_DATE on 51.0%.

## Scope

- Source: `MY_DATA_PATH/processed_data/permits_fl_sample.parquet`
- Jurisdiction: **Stuart, FL** (2,001 rows) — first `(JURISDICTION, STATE)` pair without `agent/scripts/{state}/data_repair_{state}_{city}.py`
- Script: `agent/scripts/fl/data_repair_fl_stuart.py` (`data_repair`)
- Artifact: `AGENT_DATA_PATH/stuart_repaired_sample.parquet`

## DATA schemas

| INFERRED_SCHEMA | n | Notes |
| --- | ---: | --- |
| `citizenserve_historical_building` | 747 | Named `APPLICATION DATE` / `ISSUED DATE` / `CO ISSUED DATE` or numeric ASI `17387`/`17414`/`17403` |
| `citizenserve_btr` | 387 | Business Tax Receipt (+ New Application); ASI apply/issue only |
| `citizenserve_building` | 356 | ASI `16952`/`16953`/`16955` |
| `legacy_permit_info` | 135 | Older extract: `permit_info` + `inspection_info` |
| `citizenserve_false_alarm` | 127 | Sparse dates; many null `dateCreated` |
| `citizenserve_code` | 115 | CE notice ASI + resolution ASI |
| `citizenserve_fire` | 88 | FILE from `dateCreated` only |
| `citizenserve_contractor` | 44 | Apply ASI on a subset; later dates look like renewals/expiries |
| `citizenserve_draft` | 2 | `main.status == 0` |

Canonical mappings:

| Field | CitizenServe | Legacy |
| --- | --- | --- |
| STATUS_NORMALIZED | `main.status` 0/1/2/-1 | `permit_info.Status` |
| FILE_DATE | `APPLICATION DATE` / apply ASI / `dateCreated` (**not** `dateSubmitted`) | `Application Date` |
| PERMIT_DATE | `ISSUED DATE` / issue ASI (building + BTR) | `Issued Date` |
| FINAL_DATE | `CO ISSUED DATE` / CO ASI; CE resolution ASI when Final | `C.O. Issued`, else Passed `*FINAL*` inspection |

`dateSubmitted` is deliberately ignored for FILE_DATE: on HIST building rows it frequently equals `ISSUED DATE`, while FILE_DATE already matches `dateCreated` / `APPLICATION DATE`.

## Field assessments

### STATUS_NORMALIZED

No missing values. CitizenServe `main.status` already matched STATUS_NORMALIZED 1:1 (`complete`→Final, `active`→Active, `stopped`→Inactive, `draft`→In Review).

**2 FIXED** (legacy): `Open` with an `Issued Date` had been normalized to In Review. `Open` means an open/active permit → Active. Remaining In Review rows are the 2 CitizenServe drafts.

After repair: Final 1,750; Active 176; Inactive 73; In Review 2.

### FILE_DATE

Ideal: populated for all records.

- When present (1,931 rows), FILE_DATE already equals `dateCreated` / `APPLICATION DATE` / apply ASI / legacy `Application Date` at day resolution → **0 FILLED / 0 FIXED**.
- **70** still missing: 62 False Alarm + 8 Contractor Registration HIST shells with null `dateCreated`/`dateSubmitted` and no apply ASI. Not inventable from DATA.

Coverage after repair: Active 98.9%; Final 96.1%; In Review 100%; Inactive 100%.

### PERMIT_DATE

Ideal: populated for Active and Final.

- Upstream almost empty on CitizenServe (only the 132 legacy rows with `Issued Date` were populated, and those already matched).
- **1,289 FILLED** from building/BTR issuance fields (`ISSUED DATE`, `16953`, `17414`, `17631`, `16830`).
- No incorrect existing values to overwrite (0 FIXED).
- Not filled for Code Enforcement / Fire / False Alarm / Contractor Registration (no reliable issuance key; CR later ASI dates behave like renewals).

Coverage after repair: Active 25/176 (14.2% — most Active are Fire/BTR/False Alarm without issue ASI); Final 1,376/1,750 (78.6%); In Review 0/2; Inactive 20/73.

### FINAL_DATE

Ideal: populated for Final; absent otherwise.

- Upstream: only the 91 legacy rows with `C.O. Issued` were populated (already correct).
- **801 FILLED**: 470 historical building CO, 208 building CO (`16955`), 111 CE resolution ASI (`17093`/`17596` on/after notice day), 12 legacy Passed final inspections when `C.O. Issued` blank.
- **0 FIXED** clears needed (no spurious FINAL_DATE on non-Final rows).
- Remaining Final gap: BTR / Fire / False Alarm / Contractor Registration / building rows without CO or resolution timestamps.

Coverage after repair: Final 892/1,750 (51.0%); Active / In Review / Inactive 0%.

## Repair performance

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 2 | 0 → 0 |
| FILE_DATE | 0 | 0 | 70 → 70 |
| PERMIT_DATE | 1,289 | 0 | 1,869 → 580 |
| FINAL_DATE | 801 | 0 | 1,910 → 1,109 |

## Artifacts

- Script: `agent/scripts/fl/data_repair_fl_stuart.py`
- Repaired sample: `AGENT_DATA_PATH/stuart_repaired_sample.parquet`
