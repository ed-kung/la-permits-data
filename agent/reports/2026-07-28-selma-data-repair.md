# Selma (CA) data repair

**Summary:** Selma (CA) was the first sample jurisdiction lacking a repair script (2,000 rows). CitizenServe `main`/`extra`/`location` JSON already has complete FILE_DATE (from `dateCreated`) and complete STATUS_NORMALIZED mirrored from lagged `STATUS_ORIGINAL`, but 31 rows disagree with live `main.status` and 4 Active shells carry finaling/completion stamps. PERMIT_DATE and FINAL_DATE were empty on all rows. Repair fixes 35 statuses and 69 file dates, and fills 67 permit dates and 200 final dates from named extra stamps. Most Active/Final shells still lack issuance/finaling timestamps in DATA.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order (accent-normalized city slugs). The first pair without `agent/scripts/{state}/data_repair_{state}_{city}.py` was **Selma, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

All rows share CitizenServe top-level keys `main` / `extra` / `location`. `main.status` codes map to portal lifecycle (`0=draft`, `1=active`, `2=complete`, `-1=stopped`). Variants recorded by record-type family:

| Schema | n | Description |
| --- | ---: | --- |
| `citizenserve_building_trade` | 409 | Building / trade / pool / grading / demolition / fire |
| `citizenserve_code` | 383 | Code enforcement / complaint / violation |
| `citizenserve_yard_sale` | 325 | Yard Sale Permit |
| `citizenserve_business_license` | 308 | Business license forms |
| `citizenserve_work_order` | 287 | Work Order Request (+ Completion Date) |
| `citizenserve_encroachment` | 81 | Encroachment (Issued / Finaled / Eng approval) |
| `citizenserve_solar` | 74 | Solar / SolarAPP+ |
| `citizenserve_planning` | 49 | Master planning / improvement plan |
| `citizenserve_special_event` | 27 | Special events / fireworks |
| `citizenserve_records_request` | 26 | Public records / citizen concerns |
| `citizenserve_transport` | 20 | Transportation / road closure |
| `citizenserve_form_other` | 10 | Remaining named forms |
| `empty_extra` | 1 | Empty `extra` |

Canonical fields: `main.status`, `dateSubmitted` / `dateCreated`, `Permit Issued Date` / `Permit Issue Date` / `Permit Approval Date`, `Permit Finaled Date` / `Completion Date`.

## Field assessment

### STATUS_NORMALIZED

Before: Final 878 / In Review 547 / Active 526 / Inactive 49 (0 missing). Upstream mapped 1:1 from `STATUS_ORIGINAL` (`complete`→Final, `active`→Active, `draft`→In Review, `stopped`→Inactive).

Main errors vs DATA:

- **status=2 still Active (26):** live complete code lagged behind `STATUS_ORIGINAL=active` → FIXED to Final (code enforcement, work orders, solar, mechanical, re-roof, residential building, yard sale, code complaint).
- **status=1 still Inactive (2) / Final (1):** live active code → FIXED to Active.
- **status=2 still In Review (1); status=-1 still In Review (1):** draft original lagged → FIXED to Final / Inactive.
- **Active + Permit Finaled Date (3 encroachment) / Completion Date (1 work order):** terminal stamps present while still Active → FIXED to Final.

### FILE_DATE

Fully populated. Every value equals `main.dateCreated` calendar day. Prefer `dateSubmitted` when present: **69** calendar-day disagreements (all submitted later than created) → FIXED. Coverage remains 2,000 / 2,000.

### PERMIT_DATE

Missing on 2,000 / 2,000. Fillable named stamps:

- `Permit Issued Date` (encroachment, 47)
- `Permit Issue Date` (transportation + some encroachment, 9)
- `Permit Approval Date` (pool drainage, 11)

After status promotion, **67** Active/Final rows fillable → FILLED. `City Engineer's Permit Approval Date` is plan approval and always co-occurs with an Issued/Issue stamp when usable — not used. Generic `Date`, yard-sale windows, `Date Signed`, and `expirationDate` are not issuance.

### FINAL_DATE

Missing on 2,000 / 2,000. Fillable:

- `Completion Date` on Work Order Request (190; 189 already Final + 1 promoted)
- `Permit Finaled Date` on Encroachment (10; 7 already Final + 3 promoted)

→ **200 FILLED**. Remaining Final shells (yard sale, code, business license, building/solar trades, etc.) have no finaling timestamp in DATA.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_selma.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_selma_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 0 | 35 | 0 → 0 |
| FILE_DATE | 0 | 69 | 0 → 0 |
| PERMIT_DATE | 67 | 0 | 2,000 → 1,933 |
| FINAL_DATE | 200 | 0 | 2,000 → 1,800 |

Status transitions: Active→Final 30; Inactive→Active 2; In Review→Final 1; Final→Active 1; In Review→Inactive 1.

After repair:

- FILE_DATE: 2,000 / 2,000 (100%)
- PERMIT_DATE: Active 44 / 499 (8.8%); Final 23 / 908 (2.5%)
- FINAL_DATE: Final 200 / 908 (22.0%); cleared/absent on non-Final
- Chronology: 0 FILE>PERMIT; 0 PERMIT>FINAL
- Remaining ideal gaps: 1,340 Active/Final missing PERMIT_DATE; 708 Final missing FINAL_DATE (no named stamps in DATA)
