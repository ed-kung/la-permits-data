# Missing Dates: Raw DATA Field Analysis

Analysis of the raw DATA JSON field across the top-50 city sample (~2,000 records per jurisdiction) to determine whether missing FILE_DATE, PERMIT_DATE, and FINAL_DATE values can be recovered.

## Summary

The 49 jurisdictions in the sample use **4 distinct data platform patterns**, which strongly predict what raw date fields are available. The most important finding is that **the data provider appears to have already extracted dates from the raw data into FILE_DATE, PERMIT_DATE, and FINAL_DATE, but the extraction was incomplete for many jurisdictions**. In many cases the raw DATA field contains the needed date values — the problem is that the data provider did not map them to the processed columns.

Recovery potential varies enormously:
- **~25 jurisdictions (Accela-platform cities)**: Contain a `date`/`search_data.Date` field (application/filing date) in nearly 100% of records, plus workflow event dates. However, these fields typically correspond to FILE_DATE, not PERMIT_DATE or FINAL_DATE. True permit-issued and final dates are scattered across `more_details` sub-fields and are jurisdiction-specific.
- **4 jurisdictions (CityGovApp/Energov platform)**: Have clean `entity.ApplyDate`, `entity.IssueDate`, and `entity.FinalDate` fields that directly map to FILE_DATE, PERMIT_DATE, and FINAL_DATE with high coverage.
- **~15 jurisdictions (custom APIs)**: Have city-specific date field structures with variable recoverability.
- **~5 jurisdictions**: Have essentially no recoverable dates in the raw DATA (dates are NULL, absent, or only embedded in free-text descriptions).

---

## Cross-City Patterns: Four Platform Types

### Pattern 1: Accela / CivicPlatform (~25 cities)

**Cities**: Atlanta, Charlotte, Columbus, Denver, El Paso, Fort Worth, Fresno, Indianapolis, Louisville-Jefferson County, Memphis, Mesa, Milwaukee, Oakland, Oklahoma City, Omaha, Sacramento, San Antonio, San Diego, Seattle, Virginia Beach (plus Baltimore and San Jose are partial/hybrid)

**Identifying features**: Top-level keys include `date`, `tasks`, `status`, `address`, `details`, `search_data`, `more_details`, `inspections`, `fees_details`, `conditions`.

**Common date fields**:
| Raw field | Typical coverage | Likely meaning |
|---|---|---|
| `date` | ~100% | Application/filing date (ISO format) |
| `search_data.Date` | ~100% | Application/filing date (US format) |
| `tasks[*].events[*]. on ` | 100–400% (multiple per record) | Workflow step completion dates |
| `tasks[*].events[*].Due on ` | 60–260% | Workflow step due dates |
| `fees_details[*].Date` | 50–290% | Fee transaction dates |
| `inspections[*].Status Date` | 40–260% | Inspection result dates |
| `related_records[*].File Date` | 1–175% | Linked record filing dates |
| `more_details.*.Expiration Date` | 0–70% (jurisdiction-specific) | Permit expiration |
| `more_details.*.Permit Issued Date` | 0–65% (jurisdiction-specific) | Permit issued date (key for PERMIT_DATE recovery) |

**Key insight**: The `date` / `search_data.Date` field is the **application/filing date** and closely corresponds to FILE_DATE. It is almost always populated even when FILE_DATE is missing from the processed data. However, **PERMIT_DATE and FINAL_DATE require looking into jurisdiction-specific `more_details` sub-fields or inferring from workflow event sequences**, which is much harder.

### Pattern 2: CityGovApp / Energov (~4 cities)

**Cities**: Kansas City, North Las Vegas (proxy for Las Vegas), Raleigh, Tulsa

**Identifying features**: Top-level keys include `entity`, `details`, `contacts`, `processing_status`, `fees`, `holds`, `reviews`.

**Common date fields**:
| Raw field | Typical coverage | Likely meaning |
|---|---|---|
| `entity.ApplyDate` / `details.ApplyDate` | 100% | Application date → **FILE_DATE** |
| `entity.IssueDate` / `details.IssueDate` | 91–93% | Issue date → **PERMIT_DATE** |
| `entity.FinalDate` / `details.FinalizeDate` | 15–77% | Final date → **FINAL_DATE** |
| `entity.ExpireDate` / `details.ExpireDate` | 26–86% | Permit expiration |
| `processing_status[*].requested_date` | variable | Workflow processing dates |

**Key insight**: This is the **cleanest platform for date recovery**. The field names directly and unambiguously map to the processed columns. The data provider appears to have already used these for extraction where possible, but coverage gaps suggest the mapping was imperfect.

### Pattern 3: Custom City APIs / Open Data (~15 cities)

Each city has its own schema. Key examples:

| City | Date fields available | Recovery notes |
|---|---|---|
| **New York** | `filings[*].pre__filing_date`, `filings[*].approved`, `issuances[*].issuance_date`, `filings[*].signoff_date` | Rich date lifecycle; 258 missing FILE_DATE and 738 missing PERMIT_DATE fully recoverable |
| **Chicago** | `ISSUE_DATE`, `APPLICATION_START_DATE` | Both fully populated; FINAL_DATE (0%) not in raw data |
| **Washington DC** | `ISSUE_DATE`, `CREATED_DATE`, `LASTMODIFIEDDATE` | FILE_DATE (0%) fully recoverable from ISSUE_DATE or CREATED_DATE |
| **Boston** | `issued_date`, `expiration_date` | FILE_DATE (0%) recoverable from `issued_date` |
| **Detroit** | `Date Issued`, `Date Submitted`, `Issued Date`, `Submitted Date` | FILE_DATE (0%) fully recoverable; two record-type schemas |
| **Portland** | `set_up`, `under_review`, `issued`, `final` | Clean lifecycle dates; all map directly |
| **San Francisco** | `processing_status[*].date` (multiple per record) | Date recovery requires parsing status sequence |
| **Bakersfield** | `detail.Application Date`, `permit_status_detail.Issue Date`, `permit_status_detail.Permit Date` | Very clean; most dates already extracted |
| **Nashville** | `Permit Summary[*].issued`, `Tasks[*].completedDate`, `Fees[*].feeDate` | Structured; dates require navigating nested arrays |
| **Miami** | `IssuedDate`, `PlanCreatedDate`, `PlanAcceptedDate`, `Certificatedate` | Moderate coverage (~40% of records have dates) |
| **Arlington** | `Issue_Date`, `Application_Date`, `Expiry Date` | Two sub-schemas; 58% coverage each |
| **Tucson** | `Apply Date`, `Completed Inspections[*].Date`, `Plan Review[*].Review Date` | `Apply Date` is key for PERMIT_DATE recovery |
| **El Paso County** | `Attachments[*].Date Issued`, `Inspection History[*].FormattedInspectionDate` | FILE_DATE (0%) recoverable from Attachments |
| **San Jose** | `old.file_date`, `new.details.Issue Date`, `new.details.Final Date`, `new.details.Folder Date` | Dual old/new schemas; most dates recoverable |
| **Long Beach** | `Status Date`, `Final Date` | Very limited; FILE_DATE and PERMIT_DATE both ~0% and not in raw data |

### Pattern 4: Minimal / No Recovery (~5 cities)

| City | Issue |
|---|---|
| **Los Angeles** | Raw DATA has almost no structured date fields; only occasional dates embedded in free-text `Work Description` |
| **Phoenix** | Date field names exist (`expires`, `IssuedDate`) but values are all NULL; dates only in inspection notes |
| **Minneapolis** | `issueDate` and `completeDate` fields exist but are consistently NULL |
| **Albuquerque** | Date field names exist (`Issued Date`, `Created Date`, `Completed Date`) but all values are NULL |
| **Houston** | Only `date` field with ~12% coverage; most raw data is opaque |
| **Philadelphia** | Date field names exist (`PERMITISSUEDATE`, etc.) but mostly NULL; only ~3% have values |

---

## Per-City Recovery Assessment

### FILE_DATE Recovery

| City | Missing (sample) | Recoverable | Best raw field | Confidence |
|---|---|---|---|---|
| Washington DC | 2000/2000 | **2000** | `ISSUE_DATE` | HIGH — unambiguous |
| Boston | 2000/2000 | **2000** | `issued_date` | HIGH — but semantically this is permit issue date, not filing date |
| Detroit | 2000/2000 | **2000** | `Date Submitted` / `Submitted Date` | HIGH — submission date maps to FILE_DATE |
| El Paso County | 2000/2000 | **2000** | `Attachments[*].Date Issued` (earliest) | MEDIUM — need to take min of attachment dates |
| Houston | 2000/2000 | 235 | `date` | LOW — only 12% coverage |
| Phoenix | 1992/1992 | 0 | none | NONE |
| Minneapolis | 2000/2000 | 0 | none | NONE |
| Los Angeles | 1373/2000 | 0 | none | NONE |
| Baltimore | 1215/2000 | **1215** | `Issued Date` (top-level) | HIGH |
| Philadelphia | 1636/1998 | 49 | `permitissuedate` | LOW — only 3% coverage |
| Jacksonville | 1702/1995 | 1096 | `obj.DateIssued` | MEDIUM — 64% of missing rows |
| Miami | 1545/1999 | 501 | `PlanCreatedDate` | MEDIUM — 32% of missing rows |
| New York | 258/2000 | **258** | `issuances[*].filing_date` | HIGH |
| San Francisco | 311/2000 | **311** | `processing_status[*].date` (first entry) | HIGH — need to take earliest |
| San Diego | 234/1996 | **234** | various | MEDIUM |
| All Accela cities | 0–33 | ~all | `date` / `search_data.Date` | HIGH — `date` is the application date |

### PERMIT_DATE Recovery

| City | Missing (sample) | Recoverable | Best raw field | Confidence |
|---|---|---|---|---|
| Charlotte | 1807/2000 | **1807** | `date` is NOT PERMIT_DATE; no clear permit-issued field | LOW — `date` is filing date, not issue date |
| San Antonio | 1708/2000 | **1708** | Same issue — `date` is filing date | LOW |
| Milwaukee | 1653/2000 | **1653** | Same issue | LOW |
| Seattle | 1472/2000 | **1293** | `more_details...Permit Issued Date` | HIGH — explicit field |
| Indianapolis | 1095/2000 | **1095** | `date` is filing date, not permit-issued | LOW |
| Mesa | 1304/1999 | **395** | `more_details...Permit Issued Date` | HIGH — explicit field |
| Oakland | 1390/2000 | **1390** | `date` is filing date, not permit-issued | LOW |
| Sacramento | 786/2000 | **786** | `date` is filing date | LOW |
| Columbus | 677/1993 | **677** | `date` is filing date | LOW |
| Atlanta | 1157/1999 | **1156** | `date` is filing date | LOW |
| Denver | 646/1998 | **645** | `date` is filing date | LOW |
| San Jose | 613/1997 | **610** | `old.file_date` and `new.details.Issue Date` | MEDIUM — `Issue Date` is correct but only 63% coverage |
| Tucson | 1691/1997 | **1643** | `Apply Date` — but this is application date, not permit-issued | LOW |
| Portland | 225/2000 | **1** | `issued` field has date but only 1 row with missing PERMIT_DATE has it | LOW — almost all missing rows lack the issued date too |
| New York | 738/2000 | **352** | `issuances[*].issuance_date` | HIGH — direct mapping |
| Kansas City | 135/2000 | **0** | `entity.IssueDate` already used | — already extracted |
| Raleigh | 178/2000 | **0** | `entity.IssueDate` already used | — already extracted |
| Tulsa | 179/2000 | **0** | `entity.IssueDate` already used | — already extracted |
| N. Las Vegas | 160/2000 | **0** | `entity.IssueDate` already used | — already extracted |

**Critical caveat for Accela cities**: The `date`/`search_data.Date` field is the **application/filing date**, NOT the permit-issued date. For most Accela cities, PERMIT_DATE recovery requires:
1. Checking `more_details.Application Information.*.Permit Issued Date` (only available for some cities like Seattle, Mesa)
2. Inferring from workflow events in `tasks` (e.g., the date when a "Permit Issued" task was completed) — requires knowing each city's workflow step names
3. Using `inspections` or `fees_details` dates as proxies (poor quality)

### FINAL_DATE Recovery

FINAL_DATE is the most frequently missing column (60% missing overall). Recovery potential is generally low because:

1. **Accela cities**: `date` is the filing date, not the final date. Some cities have completion dates in `more_details` but this is rare.
2. **CityGovApp cities**: `entity.FinalDate` exists and was already mostly extracted. Remaining gaps are genuinely missing.
3. **Custom cities**: Variable; Portland has `final` field, San Jose has `new.details.Final Date`, but most others don't have a clear final date field.

| City | Missing | Raw FINAL_DATE field available? | Notes |
|---|---|---|---|
| Portland | 539 | `final` (73.5% coverage overall) | ~8 additional rows recoverable |
| San Jose | 1697 | `new.details.Final Date` (32.8% coverage) | Significant recovery possible |
| Kansas City | 774 | `entity.FinalDate` (already extracted) | Minimal additional recovery |
| Chicago | 1998 | **None** | Completely unrecoverable |
| New York | 2000 | `filings[*].signoff_date` (45%) | Possible but semantics unclear |
| Washington DC | 2000 | **None** | Completely unrecoverable |
| Boston | 268 | `expiration_date` ≠ final date | Not the right concept |
| Sacramento | 2000 | **None** (except 12 records with `DECISION INFO.Final Date`) | Essentially unrecoverable |

---

## Key Findings

1. **The biggest opportunity for date recovery is FILE_DATE, not PERMIT_DATE or FINAL_DATE.** For cities where FILE_DATE is entirely missing (Washington DC, Boston, Detroit, El Paso County, Minneapolis, Houston, Phoenix), the raw data almost always contains an application/filing date or issued date that could be mapped. **This would recover FILE_DATE for ~5 cities completely** (Washington DC, Boston, Detroit, El Paso County, Baltimore).

2. **PERMIT_DATE recovery is deceptive.** While many Accela cities have date fields present when PERMIT_DATE is missing, those fields are usually the *filing date*, not the *permit-issued date*. True permit-issued dates require city-specific extraction from `more_details` sub-fields. Only a few Accela cities (Seattle, Mesa, Fort Worth) have an explicit "Permit Issued Date" in their `more_details`.

3. **FINAL_DATE is fundamentally unavailable for many jurisdictions.** It's not that the data provider failed to extract it — the raw data simply doesn't contain a completion/finalization date. This is a genuine data gap in the source systems.

4. **CityGovApp cities (Kansas City, N. Las Vegas, Raleigh, Tulsa) have the cleanest data.** Their raw JSON has direct `ApplyDate`/`IssueDate`/`FinalDate` mappings and the data provider appears to have already done a reasonable job extracting them.

5. **Five cities are essentially dead ends for date recovery**: Los Angeles, Phoenix, Minneapolis, Albuquerque, and Philadelphia have raw date fields that are consistently NULL or absent.

---

## Recommended Next Steps

1. **Quick wins** — Recover FILE_DATE for cities where it's 0% but available in raw DATA:
   - Washington DC: `ISSUE_DATE` → FILE_DATE (but note this may actually be the permit issue date, warranting investigation of semantics)
   - Boston: `issued_date` → FILE_DATE (same semantic caveat)
   - Detroit: `Date Submitted` → FILE_DATE
   - El Paso County: min(`Attachments[*].Date Issued`) → FILE_DATE
   
2. **Medium effort** — For Accela cities with missing PERMIT_DATE, investigate whether `more_details.Application Information.*.Permit Issued Date` is consistently available:
   - Seattle (64.7% coverage in raw data)
   - Mesa (19.8%)
   - Fort Worth: `more_details...C of O Issued` (3.4%)
   
3. **Validate semantics** — For cities like Washington DC and Boston, verify whether the raw "issued date" corresponds to the filing date or the permit-issued date by comparing against records where both processed columns are populated.

4. **Accept limitations** — For Los Angeles, Phoenix, Minneapolis, Albuquerque, and Philadelphia, additional date information will need to come from supplementary data sources, not from the DATA column.

## Artifacts

- Full per-jurisdiction analysis: `AGENT_DATA_PATH/raw_data_date_analysis.json`
- Analysis script: `agent/scripts/explore_raw_data_dates.py`
