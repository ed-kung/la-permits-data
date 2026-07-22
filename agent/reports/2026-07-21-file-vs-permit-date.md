# FILE_DATE vs PERMIT_DATE gap and interchangeability

**Summary:** Where both dates exist (2.84M / 7.59M rows), median `PERMIT_DATE − FILE_DATE` is **3 days** (mean 97 days, long right tail). Ordering is consistent with application→approval (only 1% have permit before file). They are **not fully interchangeable for monthly aggregates** (61% same calendar month), but monthly count series on dual-dated rows correlate at **0.996**. Coverage differences by jurisdiction matter more than the gap: City of LA is mostly permit-dated; several cities are file-only or nearly so.

## What was done

- Read `reports/2026-07-21-data-usability-report.md` (confirms many jurisdictions populate FILE and/or PERMIT; Long Beach uses FINAL; Compton FILE empty; etc.).
- Computed per-jurisdiction and overall gap stats on `MY_DATA_PATH/processed_data/dewey_ca_la_county_permits.parquet`.
- Compared period alignment (same day/month/quarter/year) and monthly series correlation.

## Main findings

### Dual-dated rows (both dates present)

| Metric | Value |
| --- | --- |
| N | 2,842,756 (37.4% of all rows) |
| Median gap (PERMIT − FILE) | 3 days |
| Mean gap | 97 days |
| p75 / p90 | 47 / 177 days |
| Same calendar day | 43% |
| Within 30 days | 70% |
| Same month / quarter / year | 61% / 72% / 87% |
| PERMIT before FILE | 1.0% |
| Monthly count correlation | 0.996 |

### Coverage (all rows)

- FILE_DATE: 55%; PERMIT_DATE: 73%; either: 91%.
- Using only one column drops large jurisdictions (e.g. Compton has no FILE; Lomita no PERMIT; Long Beach almost neither).

### Jurisdiction tiers (dual-dated behavior)

- **Close** (17): e.g. Arcadia, Claremont, Pasadena, Glendale, Torrance, LA County unincorporated — median gap ≤7d and ≥70% same month.
- **Moderate** (9): e.g. Beverly Hills, Alhambra, Culver City, Santa Clarita — small median gap but weaker month alignment and/or sparse overlap.
- **Divergent** (6): Los Angeles (City; median 31d, 39% same month), Burbank, Santa Monica, La Cañada Flintridge, Hawthorne, South El Monte.
- **No overlap** (3): Compton (PERMIT only), Lomita (FILE only), Long Beach (neither).

### Semantic interpretation

FILE≈application and PERMIT≈approval is plausible where both exist (permit almost never precedes file). Do not assume both fields are populated or interchangeable in every jurisdiction.

## Artifacts

- Script: `agent/scripts/file_vs_permit_date_gap.py`
- Script: `agent/scripts/file_vs_permit_aggregate_compare.py`
- CSV/JSON: `AGENT_DATA_PATH/file_vs_permit_date/`
- Canvas: `canvases/file-vs-permit-date.canvas.tsx` (Cursor project canvases)
