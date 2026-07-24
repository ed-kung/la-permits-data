# Compton Data Repair Assessment

Assessment of STATUS_NORMALIZED, FILE_DATE, PERMIT_DATE, and FINAL_DATE correctness for 2,000 Compton permit records using the raw DATA JSON column. A repair function was written to fix STATUS_NORMALIZED issues; date fields cannot be improved from available data.

## Data Structure

The Compton DATA column is a flat JSON with keys: `Status`, `Address`, `Permit#`, `Sub Type`, `Issue Date`, `Permit Type`, `Work Description`. There are two key-naming variants (with/without trailing spaces in `Address` and `Permit#`) and records may or may not include `Work Description`.

A significant data-quality defect affects ~417 records: the `Issue Date` field contains work-description text instead of a date, and the `Work Description` key is absent. A small number of records (3) have an even more severe column shift where `Status` contains a date and `Sub Type` contains the actual status.

## STATUS_NORMALIZED

**Before repair:** 114 missing, 2 incorrect.

### Missing statuses (114 → 113 filled, 1 unfillable)

The 114 missing values occurred because the original normalization logic did not map several DATA.Status values. The complete mapping applied by the repair:

| DATA.Status | Count | Mapped To | Notes |
|---|---|---|---|
| Voic | 40 | Inactive | Typo for "Void" |
| Approved As-is | 27 | Active | Pre-sale approved variant |
| Approved in Full Compliance | 20 | Active | Pre-sale approved variant |
| Open Substandard | 10 | Active | Active code enforcement case |
| Closed File | 5 | Inactive | Administrative file closure |
| Closed Substandard | 4 | Final | Resolved code enforcement case |
| Expired Online Submitted Application | 3 | Inactive | Expired application |
| Opening Health Food Store | 1 | Inactive | Shifted data; actual status from Sub Type = "Void" |
| 12/09/1997 | 1 | In Review | Shifted data; actual status from Sub Type = "Under Review" |
| 03/18/1998 | 1 | In Review | Shifted data; actual status from Sub Type = "Under Review" |
| not provided | 1 | In Review | Actual status from Sub Type = "Online Application Received" |
| *(no Status key)* | 1 | *(unfillable)* | No status information in DATA |

### Incorrect statuses (2 fixed)

Two records had STATUS_ORIGINAL that disagreed with DATA.Status. The DATA.Status value is authoritative:

| DATA.Status | STATUS_ORIGINAL | Old STATUS_NORMALIZED | New STATUS_NORMALIZED |
|---|---|---|---|
| Finaled | issued | Active | Final |
| Void | under review | In Review | Inactive |

### Distribution after repair

| Status | Before | After |
|---|---|---|
| Active | 1,133 | 1,189 |
| Final | 384 | 389 |
| In Review | 291 | 293 |
| Inactive | 78 | 128 |
| Missing | 114 | 1 |

## FILE_DATE

**Before repair:** All 2,000 missing. **After repair:** All 2,000 still missing.

The Compton data source does not provide a filing or application date. The only date field in DATA is `Issue Date`, which represents the permit issuance date (mapped to PERMIT_DATE). No repair is possible.

## PERMIT_DATE

**Before repair:** 417 missing. **After repair:** 417 still missing.

Where PERMIT_DATE is populated, it matches DATA.`Issue Date` exactly (1,583 records, 100% match rate). The 417 missing records fall into two groups:

- **412 records**: `Issue Date` contains work-description text instead of a date (column-shift defect at the source). No date can be recovered.
- **5 records**: `Issue Date` key is absent from DATA entirely.

After STATUS repair, the PERMIT_DATE coverage for Active and Final records:

| Status | Has PERMIT_DATE | Total | Coverage |
|---|---|---|---|
| Active | 1,097 | 1,189 | 92.3% |
| Final | 376 | 389 | 96.7% |

The 92 Active and 13 Final records without PERMIT_DATE all have the column-shift defect (Issue Date contains text, not a date).

## FINAL_DATE

**Before repair:** All 2,000 missing. **After repair:** All 2,000 still missing.

The Compton data source does not provide a finaling, completion, or sign-off date. The DATA JSON only contains `Issue Date` (permit issuance). No repair is possible for any of the 389 Final records.

## Artifacts

| File | Description |
|---|---|
| `agent/scripts/compton_data_repair.py` | Repair function `data_repair()` with CLI preview mode |
