# Mountain View (CA) data repair — 2026-07-28

Mountain View’s flat `DATA` JSON exposes only `Status` and `CompleteDate` among the fields needed here. The upstream mapper missed abbreviated status codes (`AC`, `CA`, `HO`, `MP`, plus 2 stale `FI` rows), leaving 201 null `STATUS_NORMALIZED` values. All date columns were empty; `CompleteDate` fills `FINAL_DATE` for Final rows (1,509/1,514), but `FILE_DATE` and `PERMIT_DATE` cannot be repaired because no application or issuance dates exist in DATA.

## Jurisdiction selected

First `(JURISDICTION, STATE)` pair in `permits_ca_sample.parquet` without an existing `agent/scripts/{state}/data_repair_{state}_{city}.py`: **Mountain View, CA**.

## DATA schema

Flat agency export. All 2,000 rows share keys `Status`, `Address`, `Permits`, `Const.Type`, `Description`, `CompleteDate`. Status vocabulary differs by export era:

| INFERRED_SCHEMA | n |
| --- | ---: |
| `status_abbrev` | 1,625 |
| `status_full` | 370 |
| `status_blank` | 5 |

Canonical sources:
- **STATUS_NORMALIZED** ← `Status`
- **FILE_DATE** ← *(none in DATA)*
- **PERMIT_DATE** ← *(none in DATA)*
- **FINAL_DATE** ← `CompleteDate` (Final only)

### Status → STATUS_NORMALIZED

| Status | Mapped |
| --- | --- |
| FI, Finaled, MP, Master Plan | Final |
| AC, Active | Active |
| EX, Expired, CA, Cancelled, N/A | Inactive |
| HO, Hold | In Review |

## Field assessment (before repair)

### STATUS_NORMALIZED
- Distribution: Final 1,506 / null 201 / Inactive 187 / Active 103 / In Review 3.
- Full-word statuses were mapped correctly; **abbreviated codes were not**:
  - 153× `AC` → null (should be Active)
  - 32× `CA` → null (should be Inactive)
  - 6× `MP` → null (should be Final, matching existing `Master Plan` → Final)
  - 3× `HO` → null (should be In Review, matching existing `Hold` → In Review)
  - 2× `FI` → null with `STATUS_ORIGINAL=ac` (Status advanced to finaled; original lagged)
  - 5× blank Status → null (no signal)

### FILE_DATE
- **2,000/2,000 missing.** DATA has no application/submittal date. Not fillable.

### PERMIT_DATE
- **2,000/2,000 missing.** DATA has no issuance/approval date. Not fillable (including Active/Final).

### FINAL_DATE
- **2,000/2,000 missing.**
- Among FI/Finaled: CompleteDate present on 1,505/1,506 rows (1 Finaled row empty) → fillable after status repair also covers 2 FI + MP/Master Plan with dates.
- CompleteDate also appears on Expired/Cancelled (and rare Active) rows — close/processing stamps, not used for FINAL_DATE or status promotion.

## Repair performance

Script: `agent/scripts/ca/data_repair_ca_mountain_view.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_ca_mountain_view_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 196 | 0 | 201 → 5 |
| FILE_DATE | 0 | 0 | 2,000 → 2,000 |
| PERMIT_DATE | 0 | 0 | 2,000 → 2,000 |
| FINAL_DATE | 1,509 | 0 | 2,000 → 491 |

Status fills: AC→Active (153), CA→Inactive (32), MP→Final (6), HO→In Review (3), FI→Final (2). Five blank-Status rows remain null.

### After-repair coverage

| Status | n | PERMIT_DATE | FINAL_DATE |
| --- | ---: | --- | --- |
| Active | 256 | 0/256 (0%) | 0/256 |
| Final | 1,514 | 0/1,514 (0%) | 1,509/1,514 (99.7%) |
| In Review | 6 | 0/6 | 0/6 |
| Inactive | 219 | 0/219 | 0/219 |

FILE_DATE: 0/2,000 (0%). Five Final rows lack CompleteDate (3 MP, 1 Master Plan, 1 Finaled).

## Limitations

- Mountain View’s public/export payload is status + completion only; application and issuance dates are unavailable without another source.
- Master Plan / MP are treated as Final to match the existing full-word mapper; several lack CompleteDate so FINAL_DATE stays missing.
- Blank Status rows (5) cannot be inferred from DATA.
