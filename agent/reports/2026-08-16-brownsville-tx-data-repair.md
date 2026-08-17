# Brownsville (TX) data repair

**Summary:** Brownsville was the first TX jurisdiction in `permits_tx_sample.parquet` without a repair script (1,999 rows). DATA is Accela Civic Platform (`accela` 1,991 / `search_data_only` 8). STATUS_NORMALIZED had 12 nulls and 15 incorrect mappings (Cancelled `Closed` stored as Final; `About to Expire` as Inactive). FILE_DATE was already complete and matched `DATA.date`. PERMIT_DATE had no true fills available; 261 rows used FILE_DATE instead of Permit Issuance `Issued`, and 23 Ready-to-Issue / Withdrawn rows carried spurious FILE copies → FIXED. FINAL_DATE on Final rose from 339/500 to 480/488 (98.4%) via Final Inspection / CO / Final* Passed / Modification Approved signals; spurious FINAL on non-Final rows was cleared.

## Jurisdiction selection

Loaded `MY_DATA_PATH/processed_data/permits_tx_sample.parquet` and walked unique `(JURISDICTION, STATE)` pairs in appearance order. Existing TX scripts covered through Edinburg; **Brownsville** was the first missing pair → `agent/scripts/tx/data_repair_tx_brownsville.py`.

## DATA schema

| Schema | n | Notes |
| --- | ---: | --- |
| `accela` | 1,991 | Full payload: status, date, tasks, inspections, search_data, … |
| `search_data_only` | 8 | TMP / incomplete shells; blank `search_data.Status`; FILE already from `search_data.Date` |

Canonical sources:

- `status` → STATUS_NORMALIZED
- `date` → FILE_DATE
- Permit Issuance task marked `Issued` → PERMIT_DATE
- Inspection* `Final Inspection Complete`; Certificate of Occupancy `Final CO Issued` / `Certificate Issued`; inspections Title contains Final + Status Passed; Modification Review `Modification Request Approved` → FINAL_DATE (Final only)

## Field assessment

### STATUS_NORMALIZED

Before: Inactive 1,146 / Final 500 / Active 253 / In Review 88 / missing 12.

`DATA.status` matches `STATUS_ORIGINAL` (case-normalized) on every full row. Dominant values: Permit Expired (1,079), Closed - Complete (445), Inspection Phase (242), Closed - Withdrawn (50), Ready to Issue (38), In Review (32).

Issues repaired (4 FILLED + 15 FIXED):

1. **Null status for Pending Contractor / Form Survey Required / Pending Fire Inspection (4):** filled from `DATA.status` (In Review, or Active when Issued is present).
2. **About to Expire → Inactive (3):** still-valid issued permits → FIXED to Active.
3. **Closed → Final (12):** cancelled application shells (Application Intake `Cancelled`, no issuance) → FIXED to Inactive.
4. **Form Survey Required after Issued:** Accela wording looks like In Review, but Permit Issuance `Issued` exists → treated as Active.

Left null: 8 `search_data_only` rows with blank Status.

After repair: Inactive 1,155 / Final 488 / Active 257 / In Review 91 / missing 8.

### FILE_DATE

Already 1,999 / 1,999 populated. On all `accela` rows FILE_DATE equals top-level `date` (and `search_data.Date`). Application Intake event dates are never earlier than FILE_DATE (intake acceptance can lag the record open date). No FILLED/FIXED changes.

### PERMIT_DATE

Upstream often copied FILE_DATE into PERMIT_DATE. Among 1,314 rows with a Permit Issuance `Issued` event, 1,053 already matched the earliest Issued date; **261** had PERMIT_DATE = FILE_DATE on a different day than Issued → FIXED to Issued.

**23** Ready to Issue / Closed - Withdrawn rows had PERMIT_DATE = FILE_DATE with no Issued event → cleared (FIXED).

No missing PERMIT_DATE could be filled from Issued (every Issued event already had some PERMIT_DATE). Remaining Active/Final gaps have no Issued event in DATA:

- 91 Inspection Phase (Active) — often Inspections Scheduling only; some historical shells with empty tasks
- 10 Approved (Active, ready but not issued)
- Final Closed - Complete / Closed - Approved shells without an Issued stamp

After repair by status: Active 156/257 (60.7%); Final 379/488 (77.7%); In Review 0/91 (0%); Inactive 779/1,155 (67.4%). Missing count rose 662 → 685 from clearing spurious values.

### FINAL_DATE

Before: Final 339/500 had FINAL_DATE (161 missing); 39 Inactive (mostly Permit Expired) carried spurious FINAL_DATE; Active/In Review had none.

Sources for Final completion:

- Latest Inspection / Inspection Phase `Final Inspection Complete`
- Certificate of Occupancy `Final CO Issued` / `Certificate Issued`
- inspections[] rows with Final in Title and Status Passed
- Modification Review `Modification Request Approved` (Closed - Approved admin records)

Repairs: 141 FILLED (missing Final dates from the signals above) + 57 FIXED (earlier Final Inspection Complete replaced by later stamp, or spurious non-Final FINAL cleared).

After repair: Final 480/488 (98.4%); other statuses 0%. Eight Closed - Complete shells remain without any final / CO / Final* Passed signal.

## Repair performance

Script: `agent/scripts/tx/data_repair_tx_brownsville.py`  
Artifact: `AGENT_DATA_PATH/repaired/permits_tx_brownsville_repaired.parquet`

| Field | FILLED | FIXED | Missing before → after |
| --- | ---: | ---: | --- |
| STATUS_NORMALIZED | 4 | 15 | 12 → 8 |
| FILE_DATE | 0 | 0 | 0 → 0 |
| PERMIT_DATE | 0 | 284 | 662 → 685 |
| FINAL_DATE | 141 | 57 | 1,621 → 1,519 |

Coverage after repair:

- FILE_DATE: 1,999/1,999 (100%)
- PERMIT_DATE Active/Final: 60.7% / 77.7%
- FINAL_DATE Final: 98.4%; non-Final: 0%
