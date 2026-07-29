# Imperial (CA) data repair

**Summary:** Imperial (CA) was the first sample jurisdiction lacking a repair script (2,000 rows; La Cañada Flintridge already had `data_repair_ca_la_canada_flintridge.py`). Portal Status labels already map correctly when present, but 238 rows with a passed Job Complete inspection still carried Under Review / Approved / Issued / blank status, FILE_DATE on detail rows was taken from Review Completions instead of application starts, and PERMIT_DATE / FINAL_DATE were sparse. Repair promotes those completed shells to Final, rewrites FILE_DATE from Application Intake / earliest Review Start, fills PERMIT_DATE from Final Review Completion when no parseable Issue Date exists, and fills FINAL_DATE from Job Complete. List-schema column shifts and empty Closed garage-sale shells leave many dates unrecoverable.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_ca_sample.parquet` and walked `(JURISDICTION, STATE)` in first-appearance order. Accent-normalized slug for La Cañada Flintridge already exists; the first true gap was **Imperial, CA**.

## DATA schemas (`INFERRED_SCHEMA`)

| Schema | n | Description |
| --- | ---: | --- |
| `list` | 1,315 | Search/list row: Status, Issue Date, Permit# / Permit #, Permit Type, Sub Type, optional Work Description |
| `detail` | 685 | Detail page: Status:, Permit Details, Reviews, Inspections, empty top-level Issue Date |

Canonical fields: `Status` / `Status:`, Reviews (Application Intake / Final Review), Inspections (Job Complete), parseable `Issue Date` / `Permit Details.Issue Date:`.

## Field assessment

### STATUS_NORMALIZED

Before: In Review 1,223 / missing 449 / Active 272 / Final 56.

True portal labels map cleanly and were already correct (0 mismatches):

| Portal Status | → STATUS_NORMALIZED | n |
| --- | --- | ---: |
| Under Review | In Review | 1,181 |
| Approved | Active | 235 |
| Closed | Final | 56 |
| Issued | Active | 37 |
| Online Application Received | In Review | 39 |
| Pending | In Review | 3 |

Main errors vs DATA:

- **Passed Job Complete while still In Review (141) / Active (71) / blank (26):** portal status lags completion → FIXED/FILLED to Final.
- **~244 garbage Status values** (Garage Sale Permit, PV System, patio, date fragments, etc.): STATUS_ORIGINAL mirrors the scrapes; left null unless Job Complete is present.
- **205 rows with empty Status and null STATUS_ORIGINAL:** no lifecycle signal in DATA.

### FILE_DATE

Missing on 1,674 / 2,000. On detail rows with Reviews, existing FILE_DATE matched a Review **Completion** (usually Final Review, 289; also Plans / Planning Review) rather than an application start — incorrect for FILE_DATE.

Repair source: Application Intake `Start` when present, else earliest Review `Start`.

- **115 FILLED** (missing → earliest start)
- **278 FIXED** (completion stamp → start)
- List-schema rows have no Reviews → FILE_DATE stays missing (no Applied / Submitted field). Coverage 326 → 441.

### PERMIT_DATE

Missing on 1,497 / 2,000. When list `Issue Date` is a real calendar date (379 rows; always co-occurs with Work Description), upstream already copied it into PERMIT_DATE (0 disagreements). When Work Description is absent, `Issue Date` holds work-description text (639 rows) — not usable.

For Active / Final shells without a parseable Issue Date, **Final Review Completion** fills issuance/approval: **139 FILLED**. Remaining Active / Closed Final shells have no Issue Date and no Final Review stamp.

### FINAL_DATE

Missing on 2,000 / 2,000. Fillable only from passed Job Complete inspection Date after status promotion → **238 FILLED** (81% of Final after repair). The 56 Closed Final garage-sale detail shells have empty Inspections / Issue Date / Reviews → FINAL_DATE stays missing.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_imperial.py` (`data_repair`).

Artifact: `AGENT_DATA_PATH/repaired/permits_ca_imperial_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 26 | 212 | 449 → 423 |
| FILE_DATE | 115 | 278 | 1,674 → 1,559 |
| PERMIT_DATE | 139 | 0 | 1,497 → 1,358 |
| FINAL_DATE | 238 | 0 | 2,000 → 1,762 |

Status transitions: In Review→Final 141; Active→Final 71; null→Final 26.

After repair: In Review 1,082 / missing 423 / Final 294 / Active 201. PERMIT_DATE on Active 78/201 (38.8%), Final 177/294 (60.2%). FINAL_DATE on Final 238/294 (81.0%).
