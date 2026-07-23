# Building Permits Data Usability Report

For the top 50 US cities by population. 

Key variables:

- FILE_DATE: Application date of permit
- PERMIT_DATE: Issue date of permit
- FINAL_DATE: Final date of permit
- PERMIT_OR_FILE_DATE: PERMIT_DATE if available, FILE_DATE otherwise
- STATUS_NORMALIZED: Normalized status of permit: "Active", "Final", "Inactive", "In Review"

Notes:

- This report checks the availability of the key date fields by the status of the permit and reports on the number of cities with usable data.
- This report does not de-duplicate the data. It is known that there are permit duplicates, but we have not yet investigated the extent of the problem.
- This report matches each city to a single jurisdiction in the permits data. It is possible that one city or metro area could be served by multiple jurisdictions (a jurisdiction is a building permitting authority). Thus, in real work, we'd likely want to match permits to cities based on the geocoded addresses, not on the name of the jurisdiction.
- Nuances regarding the correct interpretation of FILE_DATE, PERMIT_DATE, and FINAL_DATE may depend on the jurisdiction and warrants further investigation.
- Reported date ranges are based on 1st and 99th percentiles to avoid outliers (which are likely recording errors).



## New York, NY

- Total permits: 3,560,157
- STATUS_NORMALIZED not missing: 2,858,193 (80.3%) - **FAIL**
  - Active: 997,656 (34.9%)
    - FILE_DATE non-missing: 997,627 (100.0%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 524,987 (52.6%) [2000-2025]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 997,627 (100.0%) [2000-2025]- *OK*
  - Final: 1,627,267 (56.9%)
    - FILE_DATE non-missing: 1,627,255 (100.0%) [2000-2024]- *OK* 
    - PERMIT_DATE non-missing: 1,472,348 (90.5%) [2000-2024]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 1,627,265 (100.0%) [2000-2024]- *OK*
  - Inactive: 100,872 (3.5%)
    - FILE_DATE non-missing: 97,898 (97.1%) [2000-2024]- *OK* 
    - PERMIT_DATE non-missing: 8,343 (8.3%) [2017-2025]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 97,898 (97.1%) [2000-2024]- *OK*
  - In Review: 132,398 (4.6%)
    - FILE_DATE non-missing: 132,396 (100.0%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 2,723 (2.1%) [2007-2025]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 132,396 (100.0%) [2000-2025]- *OK*



## Los Angeles, CA

- Total permits: 4,193,329
- STATUS_NORMALIZED not missing: 3,937,445 (93.9%) - *OK*
  - Active: 507,831 (12.9%)
    - FILE_DATE non-missing: 135,906 (26.8%) [2003-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 507,769 (100.0%) [2003-2025]- *OK* 
    - FINAL_DATE non-missing: 4,648 (0.9%) [2001-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 507,820 (100.0%) [2003-2025]- *OK*
  - Final: 2,758,707 (70.1%)
    - FILE_DATE non-missing: 743,378 (26.9%) [2000-2023]- **FAIL** 
    - PERMIT_DATE non-missing: 2,757,225 (99.9%) [2000-2024]- *OK* 
    - FINAL_DATE non-missing: 2,691,841 (97.6%) [2000-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 2,757,976 (100.0%) [2000-2024]- *OK*
  - Inactive: 299,775 (7.6%)
    - FILE_DATE non-missing: 54,915 (18.3%) [2000-2023]- **FAIL** 
    - PERMIT_DATE non-missing: 274,819 (91.7%) [2000-2022]- *OK* 
    - FINAL_DATE non-missing: 3,811 (1.3%) [2000-2023]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 289,181 (96.5%) [2000-2022]- *OK*
  - In Review: 371,132 (9.4%)
    - FILE_DATE non-missing: 336,498 (90.7%) [2001-2025]- *OK* 
    - PERMIT_DATE non-missing: 20,263 (5.5%) [2001-2023]- **FAIL** 
    - FINAL_DATE non-missing: 6,666 (1.8%) [2002-2023]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 342,454 (92.3%) [2001-2025]- *OK*



## Chicago, IL

- Total permits: 819,865
- STATUS_NORMALIZED not missing: 0 (0.0%) - **FAIL**
  - Active: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - Final: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - Inactive: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - In Review: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**



## Houston, TX

- Total permits: 1,335,667
- STATUS_NORMALIZED not missing: 1,335,667 (100.0%) - *OK*
  - Active: 1,335,667 (100.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 1,319,886 (98.8%) [2018-2025]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 1,319,886 (98.8%) [2018-2025]- *OK*
  - Final: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - Inactive: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - In Review: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**



## Phoenix, AZ

- Total permits: 993,368
- STATUS_NORMALIZED not missing: 967,230 (97.4%) - *OK*
  - Active: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - Final: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - Inactive: 217,628 (22.5%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 192,848 (88.6%) [1989-2024]- *OK* 
    - FINAL_DATE non-missing: 57,057 (26.2%) [1994-2023]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 192,848 (88.6%) [1989-2024]- *OK*
  - In Review: 749,602 (77.5%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 682,249 (91.0%) [1991-2025]- *OK* 
    - FINAL_DATE non-missing: 609,724 (81.3%) [1994-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 682,249 (91.0%) [1991-2025]- *OK*



## Philadelphia, PA

- Total permits: 1,130,005
- STATUS_NORMALIZED not missing: 1,088,595 (96.3%) - *OK*
  - Active: 140,280 (12.9%)
    - FILE_DATE non-missing: 58,122 (41.4%) [2016-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 139,673 (99.6%) [2016-2025]- *OK* 
    - FINAL_DATE non-missing: 1,586 (1.1%) [2020-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 139,673 (99.6%) [2016-2025]- *OK*
  - Final: 846,130 (77.7%)
    - FILE_DATE non-missing: 109,920 (13.0%) [2017-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 845,969 (100.0%) [2007-2025]- *OK* 
    - FINAL_DATE non-missing: 820,241 (96.9%) [2007-2025]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 845,972 (100.0%) [2007-2025]- *OK*
  - Inactive: 98,933 (9.1%)
    - FILE_DATE non-missing: 27,937 (28.2%) [2011-2024]- **FAIL** 
    - PERMIT_DATE non-missing: 96,106 (97.1%) [2007-2024]- *OK* 
    - FINAL_DATE non-missing: 80,142 (81.0%) [2012-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 97,446 (98.5%) [2007-2024]- *OK*
  - In Review: 3,252 (0.3%)
    - FILE_DATE non-missing: 2,919 (89.8%) [2020-2025]- *OK* 
    - PERMIT_DATE non-missing: 416 (12.8%) [2017-2025]- **FAIL** 
    - FINAL_DATE non-missing: 207 (6.4%) [2021-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 3,161 (97.2%) [2020-2025]- *OK*



## San Antonio, TX

- Total permits: 1,085,339
- STATUS_NORMALIZED not missing: 1,058,852 (97.6%) - *OK*
  - Active: 440,651 (41.6%)
    - FILE_DATE non-missing: 435,694 (98.9%) [2005-2025]- *OK* 
    - PERMIT_DATE non-missing: 81,788 (18.6%) [2021-2025]- **FAIL** 
    - FINAL_DATE non-missing: 10,318 (2.3%) [2021-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 436,044 (99.0%) [2005-2025]- *OK*
  - Final: 402,419 (38.0%)
    - FILE_DATE non-missing: 397,903 (98.9%) [2013-2025]- *OK* 
    - PERMIT_DATE non-missing: 70,889 (17.6%) [2012-2025]- **FAIL** 
    - FINAL_DATE non-missing: 1,186 (0.3%) [2021-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 398,416 (99.0%) [2013-2025]- *OK*
  - Inactive: 146,819 (13.9%)
    - FILE_DATE non-missing: 144,905 (98.7%) [2012-2025]- *OK* 
    - PERMIT_DATE non-missing: 2,466 (1.7%) [2016-2025]- **FAIL** 
    - FINAL_DATE non-missing: 204 (0.1%) [2020-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 144,914 (98.7%) [2012-2025]- *OK*
  - In Review: 68,963 (6.5%)
    - FILE_DATE non-missing: 68,686 (99.6%) [2021-2025]- *OK* 
    - PERMIT_DATE non-missing: 401 (0.6%) [2016-2025]- **FAIL** 
    - FINAL_DATE non-missing: 637 (0.9%) [2022-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 68,693 (99.6%) [2021-2025]- *OK*



## San Diego, CA

- Total permits: 1,153,478
- STATUS_NORMALIZED not missing: 1,135,483 (98.4%) - *OK*
  - Active: 378,090 (33.3%)
    - FILE_DATE non-missing: 296,779 (78.5%) [2010-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 293,444 (77.6%) [2010-2025]- **FAIL** 
    - FINAL_DATE non-missing: 5,591 (1.5%) [2019-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 378,089 (100.0%) [2010-2025]- *OK*
  - Final: 440,298 (38.8%)
    - FILE_DATE non-missing: 432,321 (98.2%) [2009-2024]- *OK* 
    - PERMIT_DATE non-missing: 423,565 (96.2%) [2009-2024]- *OK* 
    - FINAL_DATE non-missing: 398,359 (90.5%) [2010-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 440,298 (100.0%) [2009-2024]- *OK*
  - Inactive: 97,934 (8.6%)
    - FILE_DATE non-missing: 89,190 (91.1%) [2009-2025]- *OK* 
    - PERMIT_DATE non-missing: 51,694 (52.8%) [2009-2023]- **FAIL** 
    - FINAL_DATE non-missing: 56,136 (57.3%) [2010-2021]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 95,598 (97.6%) [2009-2025]- *OK*
  - In Review: 219,161 (19.3%)
    - FILE_DATE non-missing: 194,535 (88.8%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 4,933 (2.3%) [2010-2024]- **FAIL** 
    - FINAL_DATE non-missing: 24 (0.0%) [2019-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 195,727 (89.3%) [2010-2025]- *OK*



## Dallas, TX

- Total permits: 1,011,334
- STATUS_NORMALIZED not missing: 892,511 (88.3%) - *OK*
  - Active: 112,840 (12.6%)
    - FILE_DATE non-missing: 112,840 (100.0%) [2012-2025]- *OK* 
    - PERMIT_DATE non-missing: 93,705 (83.0%) [2013-2025]- **FAIL** 
    - FINAL_DATE non-missing: 1,099 (1.0%) [2012-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 112,840 (100.0%) [2012-2025]- *OK*
  - Final: 530,641 (59.5%)
    - FILE_DATE non-missing: 530,641 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 516,266 (97.3%) [2010-2025]- *OK* 
    - FINAL_DATE non-missing: 519,549 (97.9%) [2010-2025]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 530,641 (100.0%) [2010-2025]- *OK*
  - Inactive: 208,081 (23.3%)
    - FILE_DATE non-missing: 208,081 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 82,787 (39.8%) [2010-2023]- **FAIL** 
    - FINAL_DATE non-missing: 203,987 (98.0%) [2010-2025]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 208,081 (100.0%) [2010-2025]- *OK*
  - In Review: 40,949 (4.6%)
    - FILE_DATE non-missing: 40,949 (100.0%) [2011-2025]- *OK* 
    - PERMIT_DATE non-missing: 226 (0.6%) [2011-2025]- **FAIL** 
    - FINAL_DATE non-missing: 23 (0.1%) [2025-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 40,949 (100.0%) [2011-2025]- *OK*



## Jacksonville, FL

- Total permits: 2,580,886
- STATUS_NORMALIZED not missing: 1,843,859 (71.4%) - **FAIL**
  - Active: 33,939 (1.8%)
    - FILE_DATE non-missing: 27,200 (80.1%) [2023-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 33,927 (100.0%) [2012-2025]- *OK* 
    - FINAL_DATE non-missing: 80 (0.2%) [2024-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 33,927 (100.0%) [2012-2025]- *OK*
  - Final: 1,671,135 (90.6%)
    - FILE_DATE non-missing: 314,139 (18.8%) [2000-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 1,670,980 (100.0%) [1986-2025]- *OK* 
    - FINAL_DATE non-missing: 314,078 (18.8%) [2000-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 1,670,980 (100.0%) [1986-2025]- *OK*
  - Inactive: 132,605 (7.2%)
    - FILE_DATE non-missing: 13,130 (9.9%) [2000-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 46,685 (35.2%) [1986-2024]- **FAIL** 
    - FINAL_DATE non-missing: 71 (0.1%) [2024-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 46,685 (35.2%) [1986-2024]- **FAIL**
  - In Review: 6,180 (0.3%)
    - FILE_DATE non-missing: 215 (3.5%) [2000-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 4,887 (79.1%) [1997-2023]- **FAIL** 
    - FINAL_DATE non-missing: 1 (0.0%) [2025-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 4,887 (79.1%) [1997-2023]- **FAIL**



## Austin, TX

- Total permits: 4,591,194
- STATUS_NORMALIZED not missing: 4,590,245 (100.0%) - *OK*
  - Active: 107,717 (2.3%)
    - FILE_DATE non-missing: 102,161 (94.8%) [2015-2025]- *OK* 
    - PERMIT_DATE non-missing: 102,169 (94.8%) [2019-2025]- *OK* 
    - FINAL_DATE non-missing: 1,342 (1.2%) [1982-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 102,169 (94.8%) [2019-2025]- *OK*
  - Final: 3,822,211 (83.3%)
    - FILE_DATE non-missing: 3,820,845 (100.0%) [1981-2024]- *OK* 
    - PERMIT_DATE non-missing: 3,820,889 (100.0%) [1981-2024]- *OK* 
    - FINAL_DATE non-missing: 3,819,152 (99.9%) [1981-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 3,820,889 (100.0%) [1981-2024]- *OK*
  - Inactive: 659,844 (14.4%)
    - FILE_DATE non-missing: 659,824 (100.0%) [1980-2023]- *OK* 
    - PERMIT_DATE non-missing: 659,830 (100.0%) [1980-2023]- *OK* 
    - FINAL_DATE non-missing: 341,986 (51.8%) [1980-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 659,830 (100.0%) [1980-2023]- *OK*
  - In Review: 473 (0.0%)
    - FILE_DATE non-missing: 465 (98.3%) [1981-2025]- *OK* 
    - PERMIT_DATE non-missing: 465 (98.3%) [1981-2025]- *OK* 
    - FINAL_DATE non-missing: 330 (69.8%) [1981-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 465 (98.3%) [1981-2025]- *OK*



## Fort Worth, TX

- Total permits: 1,514,568
- STATUS_NORMALIZED not missing: 1,507,103 (99.5%) - *OK*
  - Active: 182,376 (12.1%)
    - FILE_DATE non-missing: 182,373 (100.0%) [2011-2025]- *OK* 
    - PERMIT_DATE non-missing: 171,332 (93.9%) [2011-2025]- *OK* 
    - FINAL_DATE non-missing: 1,276 (0.7%) [2013-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 182,374 (100.0%) [2011-2025]- *OK*
  - Final: 973,253 (64.6%)
    - FILE_DATE non-missing: 973,248 (100.0%) [2001-2025]- *OK* 
    - PERMIT_DATE non-missing: 966,272 (99.3%) [2002-2025]- *OK* 
    - FINAL_DATE non-missing: 590,931 (60.7%) [2013-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 973,252 (100.0%) [2001-2025]- *OK*
  - Inactive: 319,151 (21.2%)
    - FILE_DATE non-missing: 319,151 (100.0%) [2000-2021]- *OK* 
    - PERMIT_DATE non-missing: 179,907 (56.4%) [2002-2021]- **FAIL** 
    - FINAL_DATE non-missing: 1,144 (0.4%) [2014-2021]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 319,151 (100.0%) [2000-2021]- *OK*
  - In Review: 32,323 (2.1%)
    - FILE_DATE non-missing: 32,304 (99.9%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 1,224 (3.8%) [2010-2025]- **FAIL** 
    - FINAL_DATE non-missing: 71 (0.2%) [2014-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 32,304 (99.9%) [2010-2025]- *OK*



## San Jose, CA

- Total permits: 613,194
- STATUS_NORMALIZED not missing: 613,187 (100.0%) - *OK*
  - Active: 113,852 (18.6%)
    - FILE_DATE non-missing: 113,637 (99.8%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 100,145 (88.0%) [2010-2025]- *OK* 
    - FINAL_DATE non-missing: 741 (0.7%) [2012-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 113,802 (100.0%) [2010-2025]- *OK*
  - Final: 299,786 (48.9%)
    - FILE_DATE non-missing: 298,692 (99.6%) [2009-2025]- *OK* 
    - PERMIT_DATE non-missing: 255,012 (85.1%) [2009-2025]- *OK* 
    - FINAL_DATE non-missing: 86,340 (28.8%) [2010-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 299,123 (99.8%) [2009-2025]- *OK*
  - Inactive: 112,321 (18.3%)
    - FILE_DATE non-missing: 112,024 (99.7%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 59,922 (53.3%) [2009-2023]- **FAIL** 
    - FINAL_DATE non-missing: 1,935 (1.7%) [2010-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 112,033 (99.7%) [2010-2025]- *OK*
  - In Review: 87,228 (14.2%)
    - FILE_DATE non-missing: 86,953 (99.7%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 13,670 (15.7%) [2011-2025]- **FAIL** 
    - FINAL_DATE non-missing: 28 (0.0%) [2010-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 86,959 (99.7%) [2010-2025]- *OK*



## Columbus, OH

- Total permits: 1,009,373
- STATUS_NORMALIZED not missing: 863,677 (85.6%) - *OK*
  - Active: 186,584 (21.6%)
    - FILE_DATE non-missing: 186,584 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 169,504 (90.8%) [2011-2025]- *OK* 
    - FINAL_DATE non-missing: 2 (0.0%) [2020-2020]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 186,584 (100.0%) [2011-2025]- *OK*
  - Final: 636,302 (73.7%)
    - FILE_DATE non-missing: 636,302 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 473,766 (74.5%) [2010-2024]- **FAIL** 
    - FINAL_DATE non-missing: 65 (0.0%) [2011-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 636,302 (100.0%) [2010-2025]- *OK*
  - Inactive: 31,279 (3.6%)
    - FILE_DATE non-missing: 31,279 (100.0%) [2009-2025]- *OK* 
    - PERMIT_DATE non-missing: 20,054 (64.1%) [2009-2023]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 31,279 (100.0%) [2009-2025]- *OK*
  - In Review: 9,512 (1.1%)
    - FILE_DATE non-missing: 9,512 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 93 (1.0%) [2012-2025]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 9,512 (100.0%) [2010-2025]- *OK*



## Charlotte, NC

- Total permits: 124,770
- STATUS_NORMALIZED not missing: 103,310 (82.8%) - **FAIL**
  - Active: 27,060 (26.2%)
    - FILE_DATE non-missing: 27,060 (100.0%) [2008-2025]- *OK* 
    - PERMIT_DATE non-missing: 9,242 (34.2%) [2008-2025]- **FAIL** 
    - FINAL_DATE non-missing: 2,287 (8.5%) [2008-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 27,060 (100.0%) [2008-2025]- *OK*
  - Final: 20,925 (20.3%)
    - FILE_DATE non-missing: 20,925 (100.0%) [2005-2025]- *OK* 
    - PERMIT_DATE non-missing: 2,218 (10.6%) [2007-2023]- **FAIL** 
    - FINAL_DATE non-missing: 3,881 (18.5%) [2008-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 20,925 (100.0%) [2007-2025]- *OK*
  - Inactive: 5,372 (5.2%)
    - FILE_DATE non-missing: 5,372 (100.0%) [2007-2025]- *OK* 
    - PERMIT_DATE non-missing: 13 (0.2%) [2008-2025]- **FAIL** 
    - FINAL_DATE non-missing: 12 (0.2%) [2008-2023]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 5,372 (100.0%) [2007-2025]- *OK*
  - In Review: 49,953 (48.4%)
    - FILE_DATE non-missing: 49,953 (100.0%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 155 (0.3%) [2023-2025]- **FAIL** 
    - FINAL_DATE non-missing: 123 (0.2%) [2008-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 49,953 (100.0%) [2000-2025]- *OK*



## Indianapolis, IN

- Total permits: 720,783
- STATUS_NORMALIZED not missing: 675,278 (93.7%) - *OK*
  - Active: 253,289 (37.5%)
    - FILE_DATE non-missing: 253,289 (100.0%) [2000-2022]- *OK* 
    - PERMIT_DATE non-missing: 137,888 (54.4%) [2012-2022]- **FAIL** 
    - FINAL_DATE non-missing: 10,820 (4.3%) [2010-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 253,289 (100.0%) [2000-2022]- *OK*
  - Final: 300,197 (44.5%)
    - FILE_DATE non-missing: 300,197 (100.0%) [2000-2022]- *OK* 
    - PERMIT_DATE non-missing: 175,729 (58.5%) [2012-2022]- **FAIL** 
    - FINAL_DATE non-missing: 142,736 (47.5%) [2013-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 300,197 (100.0%) [2000-2022]- *OK*
  - Inactive: 25,048 (3.7%)
    - FILE_DATE non-missing: 25,048 (100.0%) [2000-2022]- *OK* 
    - PERMIT_DATE non-missing: 5,192 (20.7%) [2011-2022]- **FAIL** 
    - FINAL_DATE non-missing: 20 (0.1%) [2013-2021]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 25,048 (100.0%) [2000-2022]- *OK*
  - In Review: 96,744 (14.3%)
    - FILE_DATE non-missing: 96,744 (100.0%) [2000-2022]- *OK* 
    - PERMIT_DATE non-missing: 858 (0.9%) [2013-2022]- **FAIL** 
    - FINAL_DATE non-missing: 130 (0.1%) [2013-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 96,744 (100.0%) [2000-2022]- *OK*



## San Francisco, CA

- Total permits: 603,235
- STATUS_NORMALIZED not missing: 602,259 (99.8%) - *OK*
  - Active: 227,264 (37.7%)
    - FILE_DATE non-missing: 143,065 (63.0%) [2010-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 226,682 (99.7%) [2010-2025]- *OK* 
    - FINAL_DATE non-missing: 65,611 (28.9%) [2010-2021]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 227,264 (100.0%) [2010-2025]- *OK*
  - Final: 256,922 (42.7%)
    - FILE_DATE non-missing: 256,921 (100.0%) [2010-2024]- *OK* 
    - PERMIT_DATE non-missing: 256,838 (100.0%) [2010-2024]- *OK* 
    - FINAL_DATE non-missing: 256,920 (100.0%) [2010-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 256,921 (100.0%) [2010-2024]- *OK*
  - Inactive: 19,620 (3.3%)
    - FILE_DATE non-missing: 19,144 (97.6%) [2010-2023]- *OK* 
    - PERMIT_DATE non-missing: 11,298 (57.6%) [2010-2023]- **FAIL** 
    - FINAL_DATE non-missing: 100 (0.5%) [2010-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 19,144 (97.6%) [2010-2023]- *OK*
  - In Review: 98,453 (16.3%)
    - FILE_DATE non-missing: 98,446 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 66,644 (67.7%) [2010-2021]- **FAIL** 
    - FINAL_DATE non-missing: 51,675 (52.5%) [2010-2021]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 98,446 (100.0%) [2010-2025]- *OK*



## Seattle, WA

- Total permits: 1,389,714
- STATUS_NORMALIZED not missing: 1,389,609 (100.0%) - *OK*
  - Active: 104,572 (7.5%)
    - FILE_DATE non-missing: 104,572 (100.0%) [2014-2025]- *OK* 
    - PERMIT_DATE non-missing: 100,236 (95.9%) [2018-2025]- *OK* 
    - FINAL_DATE non-missing: 247 (0.2%) [2018-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 104,572 (100.0%) [2014-2025]- *OK*
  - Final: 1,127,455 (81.1%)
    - FILE_DATE non-missing: 1,127,455 (100.0%) [2003-2025]- *OK* 
    - PERMIT_DATE non-missing: 251,155 (22.3%) [2018-2025]- **FAIL** 
    - FINAL_DATE non-missing: 238,359 (21.1%) [2018-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 1,127,455 (100.0%) [2003-2025]- *OK*
  - Inactive: 91,634 (6.6%)
    - FILE_DATE non-missing: 91,634 (100.0%) [2003-2025]- *OK* 
    - PERMIT_DATE non-missing: 27,726 (30.3%) [2018-2025]- **FAIL** 
    - FINAL_DATE non-missing: 467 (0.5%) [2007-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 91,634 (100.0%) [2003-2025]- *OK*
  - In Review: 65,948 (4.7%)
    - FILE_DATE non-missing: 65,948 (100.0%) [2008-2025]- *OK* 
    - PERMIT_DATE non-missing: 1,880 (2.9%) [2018-2025]- **FAIL** 
    - FINAL_DATE non-missing: 257 (0.4%) [2019-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 65,948 (100.0%) [2008-2025]- *OK*



## Denver, CO

- Total permits: 2,250,718
- STATUS_NORMALIZED not missing: 2,242,011 (99.6%) - *OK*
  - Active: 209,322 (9.3%)
    - FILE_DATE non-missing: 202,822 (96.9%) [2003-2025]- *OK* 
    - PERMIT_DATE non-missing: 206,903 (98.8%) [2002-2025]- *OK* 
    - FINAL_DATE non-missing: 5 (0.0%) [2018-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 209,288 (100.0%) [2002-2025]- *OK*
  - Final: 1,697,885 (75.7%)
    - FILE_DATE non-missing: 1,691,145 (99.6%) [2002-2024]- *OK* 
    - PERMIT_DATE non-missing: 1,181,407 (69.6%) [1999-2024]- **FAIL** 
    - FINAL_DATE non-missing: 10,990 (0.6%) [2016-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 1,695,582 (99.9%) [1999-2024]- *OK*
  - Inactive: 162,113 (7.2%)
    - FILE_DATE non-missing: 161,500 (99.6%) [2002-2025]- *OK* 
    - PERMIT_DATE non-missing: 89,060 (54.9%) [1999-2023]- **FAIL** 
    - FINAL_DATE non-missing: 3,206 (2.0%) [2015-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 161,562 (99.7%) [1999-2025]- *OK*
  - In Review: 172,691 (7.7%)
    - FILE_DATE non-missing: 167,490 (97.0%) [2001-2025]- *OK* 
    - PERMIT_DATE non-missing: 2,358 (1.4%) [2015-2025]- **FAIL** 
    - FINAL_DATE non-missing: 993 (0.6%) [2016-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 167,575 (97.0%) [2001-2025]- *OK*



## Oklahoma City, OK

- Total permits: 1,092,870
- STATUS_NORMALIZED not missing: 928,929 (85.0%) - **FAIL**
  - Active: 89,160 (9.6%)
    - FILE_DATE non-missing: 89,160 (100.0%) [2004-2025]- *OK* 
    - PERMIT_DATE non-missing: 75,359 (84.5%) [2008-2025]- **FAIL** 
    - FINAL_DATE non-missing: 4,427 (5.0%) [2007-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 89,160 (100.0%) [2004-2025]- *OK*
  - Final: 822,860 (88.6%)
    - FILE_DATE non-missing: 822,860 (100.0%) [2004-2025]- *OK* 
    - PERMIT_DATE non-missing: 665,544 (80.9%) [2007-2025]- **FAIL** 
    - FINAL_DATE non-missing: 597,161 (72.6%) [2007-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 822,860 (100.0%) [2004-2025]- *OK*
  - Inactive: 6,313 (0.7%)
    - FILE_DATE non-missing: 6,313 (100.0%) [2004-2024]- *OK* 
    - PERMIT_DATE non-missing: 1,635 (25.9%) [2007-2020]- **FAIL** 
    - FINAL_DATE non-missing: 16 (0.3%) [2007-2020]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 6,313 (100.0%) [2004-2024]- *OK*
  - In Review: 10,596 (1.1%)
    - FILE_DATE non-missing: 10,596 (100.0%) [2007-2025]- *OK* 
    - PERMIT_DATE non-missing: 352 (3.3%) [2007-2025]- **FAIL** 
    - FINAL_DATE non-missing: 21 (0.2%) [2008-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 10,596 (100.0%) [2007-2025]- *OK*



## Nashville, TN

- Total permits: 709,261
- STATUS_NORMALIZED not missing: 708,186 (99.8%) - *OK*
  - Active: 92,296 (13.0%)
    - FILE_DATE non-missing: 91,868 (99.5%) [1989-2025]- *OK* 
    - PERMIT_DATE non-missing: 91,872 (99.5%) [1989-2025]- *OK* 
    - FINAL_DATE non-missing: 148 (0.2%) [2007-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 91,872 (99.5%) [1989-2025]- *OK*
  - Final: 16,396 (2.3%)
    - FILE_DATE non-missing: 16,312 (99.5%) [2007-2025]- *OK* 
    - PERMIT_DATE non-missing: 16,317 (99.5%) [2006-2025]- *OK* 
    - FINAL_DATE non-missing: 1,043 (6.4%) [2019-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 16,317 (99.5%) [2006-2025]- *OK*
  - Inactive: 140,558 (19.8%)
    - FILE_DATE non-missing: 133,237 (94.8%) [1980-2024]- *OK* 
    - PERMIT_DATE non-missing: 133,238 (94.8%) [1980-2024]- *OK* 
    - FINAL_DATE non-missing: 69,123 (49.2%) [1982-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 133,238 (94.8%) [1980-2024]- *OK*
  - In Review: 458,936 (64.8%)
    - FILE_DATE non-missing: 432,395 (94.2%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 432,395 (94.2%) [2000-2025]- *OK* 
    - FINAL_DATE non-missing: 136,120 (29.7%) [2016-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 432,395 (94.2%) [2000-2025]- *OK*



## Washington, DC

- Total permits: 728,068
- STATUS_NORMALIZED not missing: 727,792 (100.0%) - *OK*
  - Active: 519,798 (71.4%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 519,798 (100.0%) [2009-2025]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 519,798 (100.0%) [2009-2025]- *OK*
  - Final: 204,724 (28.1%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 204,724 (100.0%) [2009-2025]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 204,724 (100.0%) [2009-2025]- *OK*
  - Inactive: 2,509 (0.3%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 2,509 (100.0%) [2011-2025]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 2,509 (100.0%) [2011-2025]- *OK*
  - In Review: 761 (0.1%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 761 (100.0%) [2009-2025]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 761 (100.0%) [2009-2025]- *OK*



## El Paso, TX

- Total permits: 653,643
- STATUS_NORMALIZED not missing: 647,743 (99.1%) - *OK*
  - Active: 191,257 (29.5%)
    - FILE_DATE non-missing: 191,257 (100.0%) [2009-2025]- *OK* 
    - PERMIT_DATE non-missing: 153,650 (80.3%) [2011-2025]- **FAIL** 
    - FINAL_DATE non-missing: 3 (0.0%) [2025-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 191,257 (100.0%) [2009-2025]- *OK*
  - Final: 370,468 (57.2%)
    - FILE_DATE non-missing: 370,468 (100.0%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 291,506 (78.7%) [2011-2025]- **FAIL** 
    - FINAL_DATE non-missing: 198 (0.1%) [2015-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 370,468 (100.0%) [2000-2025]- *OK*
  - Inactive: 75,972 (11.7%)
    - FILE_DATE non-missing: 75,972 (100.0%) [2000-2024]- *OK* 
    - PERMIT_DATE non-missing: 58,945 (77.6%) [2011-2023]- **FAIL** 
    - FINAL_DATE non-missing: 2 (0.0%) [2025-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 75,972 (100.0%) [2000-2024]- *OK*
  - In Review: 10,046 (1.6%)
    - FILE_DATE non-missing: 10,046 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 289 (2.9%) [2012-2024]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 10,046 (100.0%) [2010-2025]- *OK*



## Las Vegas, NV

*Note: The best match for Las Vegas, NV in the permits data was North Las Vegas, NV*.

- Total permits: 166,366
- STATUS_NORMALIZED not missing: 166,366 (100.0%) - *OK*
  - Active: 79,072 (47.5%)
    - FILE_DATE non-missing: 79,072 (100.0%) [2009-2025]- *OK* 
    - PERMIT_DATE non-missing: 77,779 (98.4%) [2009-2025]- *OK* 
    - FINAL_DATE non-missing: 167 (0.2%) [2011-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 79,072 (100.0%) [2009-2025]- *OK*
  - Final: 25,434 (15.3%)
    - FILE_DATE non-missing: 25,434 (100.0%) [2019-2025]- *OK* 
    - PERMIT_DATE non-missing: 25,096 (98.7%) [2019-2025]- *OK* 
    - FINAL_DATE non-missing: 25,431 (100.0%) [2019-2025]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 25,434 (100.0%) [2019-2025]- *OK*
  - Inactive: 50,965 (30.6%)
    - FILE_DATE non-missing: 50,965 (100.0%) [2011-2025]- *OK* 
    - PERMIT_DATE non-missing: 48,389 (94.9%) [2011-2025]- *OK* 
    - FINAL_DATE non-missing: 39 (0.1%) [2019-2023]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 50,965 (100.0%) [2011-2025]- *OK*
  - In Review: 10,895 (6.5%)
    - FILE_DATE non-missing: 10,895 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 980 (9.0%) [2011-2025]- **FAIL** 
    - FINAL_DATE non-missing: 15 (0.1%) [2020-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 10,895 (100.0%) [2010-2025]- *OK*



## Boston, MA

- Total permits: 648,600
- STATUS_NORMALIZED not missing: 648,600 (100.0%) - *OK*
  - Active: 3 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 3 (100.0%) [2010-2019]- *OK* 
    - FINAL_DATE non-missing: 3 (100.0%) [2011-2020]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 3 (100.0%) [2010-2019]- *OK*
  - Final: 236,077 (36.4%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 236,077 (100.0%) [2010-2025]- *OK* 
    - FINAL_DATE non-missing: 202,930 (86.0%) [2010-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 236,077 (100.0%) [2010-2025]- *OK*
  - Inactive: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - In Review: 412,520 (63.6%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 412,520 (100.0%) [2010-2025]- *OK* 
    - FINAL_DATE non-missing: 347,661 (84.3%) [2010-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 412,520 (100.0%) [2010-2025]- *OK*



## Detroit, MI

- Total permits: 42,625
- STATUS_NORMALIZED not missing: 37,374 (87.7%) - *OK*
  - Active: 37,374 (100.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 37,374 (100.0%) [2019-2025]- *OK* 
    - FINAL_DATE non-missing: 37,370 (100.0%) [2019-2025]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 37,374 (100.0%) [2019-2025]- *OK*
  - Final: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - Inactive: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - In Review: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**



## Portland, OR

- Total permits: 1,447,671
- STATUS_NORMALIZED not missing: 1,419,141 (98.0%) - *OK*
  - Active: 122,448 (8.6%)
    - FILE_DATE non-missing: 122,448 (100.0%) [2001-2025]- *OK* 
    - PERMIT_DATE non-missing: 119,188 (97.3%) [2002-2025]- *OK* 
    - FINAL_DATE non-missing: 675 (0.6%) [2000-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 122,448 (100.0%) [2001-2025]- *OK*
  - Final: 1,096,226 (77.2%)
    - FILE_DATE non-missing: 1,096,226 (100.0%) [2000-2024]- *OK* 
    - PERMIT_DATE non-missing: 1,009,224 (92.1%) [2000-2024]- *OK* 
    - FINAL_DATE non-missing: 1,044,736 (95.3%) [2000-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 1,096,226 (100.0%) [2000-2024]- *OK*
  - Inactive: 165,259 (11.6%)
    - FILE_DATE non-missing: 165,259 (100.0%) [2000-2023]- *OK* 
    - PERMIT_DATE non-missing: 151,890 (91.9%) [2000-2023]- *OK* 
    - FINAL_DATE non-missing: 799 (0.5%) [2000-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 165,259 (100.0%) [2000-2023]- *OK*
  - In Review: 35,208 (2.5%)
    - FILE_DATE non-missing: 35,208 (100.0%) [2002-2025]- *OK* 
    - PERMIT_DATE non-missing: 3,810 (10.8%) [2001-2025]- **FAIL** 
    - FINAL_DATE non-missing: 401 (1.1%) [2001-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 35,208 (100.0%) [2002-2025]- *OK*



## Louisville, KY

*Note: The best match for Louisville, KY in the permits data was Louisville-Jefferson County, KY*.

- Total permits: 495,824
- STATUS_NORMALIZED not missing: 494,547 (99.7%) - *OK*
  - Active: 59,988 (12.1%)
    - FILE_DATE non-missing: 59,988 (100.0%) [2014-2025]- *OK* 
    - PERMIT_DATE non-missing: 59,915 (99.9%) [2014-2025]- *OK* 
    - FINAL_DATE non-missing: 6,495 (10.8%) [2014-2020]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 59,988 (100.0%) [2014-2025]- *OK*
  - Final: 151,722 (30.7%)
    - FILE_DATE non-missing: 151,722 (100.0%) [2004-2025]- *OK* 
    - PERMIT_DATE non-missing: 149,812 (98.7%) [2013-2025]- *OK* 
    - FINAL_DATE non-missing: 87,888 (57.9%) [2013-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 151,722 (100.0%) [2012-2025]- *OK*
  - Inactive: 275,285 (55.7%)
    - FILE_DATE non-missing: 275,285 (100.0%) [2004-2023]- *OK* 
    - PERMIT_DATE non-missing: 250,161 (90.9%) [2013-2023]- *OK* 
    - FINAL_DATE non-missing: 148,819 (54.1%) [2013-2018]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 275,285 (100.0%) [2008-2023]- *OK*
  - In Review: 7,552 (1.5%)
    - FILE_DATE non-missing: 7,552 (100.0%) [2006-2025]- *OK* 
    - PERMIT_DATE non-missing: 26 (0.3%) [2020-2025]- **FAIL** 
    - FINAL_DATE non-missing: 3 (0.0%) [2006-2020]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 7,552 (100.0%) [2006-2025]- *OK*



## Memphis, TN

- Total permits: 1,007,920
- STATUS_NORMALIZED not missing: 1,001,620 (99.4%) - *OK*
  - Active: 110,791 (11.1%)
    - FILE_DATE non-missing: 110,791 (100.0%) [2014-2025]- *OK* 
    - PERMIT_DATE non-missing: 104,045 (93.9%) [2018-2025]- *OK* 
    - FINAL_DATE non-missing: 319 (0.3%) [2007-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 110,791 (100.0%) [2014-2025]- *OK*
  - Final: 732,531 (73.1%)
    - FILE_DATE non-missing: 732,531 (100.0%) [2002-2025]- *OK* 
    - PERMIT_DATE non-missing: 669,488 (91.4%) [2003-2025]- *OK* 
    - FINAL_DATE non-missing: 665,272 (90.8%) [2003-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 732,531 (100.0%) [2002-2025]- *OK*
  - Inactive: 148,346 (14.8%)
    - FILE_DATE non-missing: 148,346 (100.0%) [2003-2024]- *OK* 
    - PERMIT_DATE non-missing: 126,626 (85.4%) [2003-2022]- *OK* 
    - FINAL_DATE non-missing: 643 (0.4%) [2002-2023]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 148,346 (100.0%) [2003-2024]- *OK*
  - In Review: 9,952 (1.0%)
    - FILE_DATE non-missing: 9,952 (100.0%) [2020-2025]- *OK* 
    - PERMIT_DATE non-missing: 86 (0.9%) [2020-2025]- **FAIL** 
    - FINAL_DATE non-missing: 5 (0.1%) [2022-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 9,952 (100.0%) [2020-2025]- *OK*



## Baltimore, MD

- Total permits: 744,379
- STATUS_NORMALIZED not missing: 282,655 (38.0%) - **FAIL**
  - Active: 17,962 (6.4%)
    - FILE_DATE non-missing: 17,962 (100.0%) [2020-2025]- *OK* 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 17,962 (100.0%) [2020-2025]- *OK*
  - Final: 80,185 (28.4%)
    - FILE_DATE non-missing: 80,185 (100.0%) [2019-2025]- *OK* 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 80,185 (100.0%) [2019-2025]- *OK*
  - Inactive: 168,091 (59.5%)
    - FILE_DATE non-missing: 168,091 (100.0%) [2020-2025]- *OK* 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 168,091 (100.0%) [2020-2025]- *OK*
  - In Review: 16,417 (5.8%)
    - FILE_DATE non-missing: 16,417 (100.0%) [2020-2025]- *OK* 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 16,417 (100.0%) [2020-2025]- *OK*



## Milwaukee, WI

- Total permits: 2,290,903
- STATUS_NORMALIZED not missing: 2,067,894 (90.3%) - *OK*
  - Active: 294,906 (14.3%)
    - FILE_DATE non-missing: 285,405 (96.8%) [2015-2025]- *OK* 
    - PERMIT_DATE non-missing: 90,590 (30.7%) [2017-2025]- **FAIL** 
    - FINAL_DATE non-missing: 561 (0.2%) [2016-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 292,917 (99.3%) [2015-2025]- *OK*
  - Final: 1,446,485 (69.9%)
    - FILE_DATE non-missing: 1,415,271 (97.8%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 288,010 (19.9%) [2010-2025]- **FAIL** 
    - FINAL_DATE non-missing: 138,743 (9.6%) [2016-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 1,440,589 (99.6%) [2010-2025]- *OK*
  - Inactive: 130,514 (6.3%)
    - FILE_DATE non-missing: 128,003 (98.1%) [2015-2025]- *OK* 
    - PERMIT_DATE non-missing: 12,340 (9.5%) [2014-2024]- **FAIL** 
    - FINAL_DATE non-missing: 130 (0.1%) [2016-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 129,747 (99.4%) [2015-2025]- *OK*
  - In Review: 195,989 (9.5%)
    - FILE_DATE non-missing: 191,096 (97.5%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 5,829 (3.0%) [2016-2025]- **FAIL** 
    - FINAL_DATE non-missing: 2,323 (1.2%) [2016-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 191,803 (97.9%) [2010-2025]- *OK*



## Albuquerque, NM

- Total permits: 354,292
- STATUS_NORMALIZED not missing: 175,966 (49.7%) - **FAIL**
  - Active: 11,507 (6.5%)
    - FILE_DATE non-missing: 11,507 (100.0%) [2022-2025]- *OK* 
    - PERMIT_DATE non-missing: 11,439 (99.4%) [2022-2025]- *OK* 
    - FINAL_DATE non-missing: 117 (1.0%) [2019-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 11,507 (100.0%) [2022-2025]- *OK*
  - Final: 70,259 (39.9%)
    - FILE_DATE non-missing: 70,259 (100.0%) [2016-2024]- *OK* 
    - PERMIT_DATE non-missing: 70,209 (99.9%) [2016-2024]- *OK* 
    - FINAL_DATE non-missing: 70,259 (100.0%) [2017-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 70,259 (100.0%) [2016-2024]- *OK*
  - Inactive: 51,156 (29.1%)
    - FILE_DATE non-missing: 51,156 (100.0%) [2016-2023]- *OK* 
    - PERMIT_DATE non-missing: 48,886 (95.6%) [2016-2023]- *OK* 
    - FINAL_DATE non-missing: 51,156 (100.0%) [2018-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 51,156 (100.0%) [2016-2023]- *OK*
  - In Review: 43,044 (24.5%)
    - FILE_DATE non-missing: 43,044 (100.0%) [2016-2024]- *OK* 
    - PERMIT_DATE non-missing: 128 (0.3%) [2016-2024]- **FAIL** 
    - FINAL_DATE non-missing: 24 (0.1%) [2017-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 43,044 (100.0%) [2016-2024]- *OK*



## Tucson, AZ

- Total permits: 637,131
- STATUS_NORMALIZED not missing: 507,982 (79.7%) - **FAIL**
  - Active: 22,201 (4.4%)
    - FILE_DATE non-missing: 22,201 (100.0%) [2000-2023]- *OK* 
    - PERMIT_DATE non-missing: 1,518 (6.8%) [2008-2022]- **FAIL** 
    - FINAL_DATE non-missing: 204 (0.9%) [2007-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 22,201 (100.0%) [2000-2023]- *OK*
  - Final: 354,805 (69.8%)
    - FILE_DATE non-missing: 354,805 (100.0%) [2000-2022]- *OK* 
    - PERMIT_DATE non-missing: 88,128 (24.8%) [2000-2021]- **FAIL** 
    - FINAL_DATE non-missing: 258,163 (72.8%) [2000-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 354,805 (100.0%) [2000-2022]- *OK*
  - Inactive: 117,545 (23.1%)
    - FILE_DATE non-missing: 104,212 (88.7%) [2000-2022]- *OK* 
    - PERMIT_DATE non-missing: 15,937 (13.6%) [2000-2021]- **FAIL** 
    - FINAL_DATE non-missing: 22,406 (19.1%) [2000-2019]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 104,509 (88.9%) [2000-2022]- *OK*
  - In Review: 13,431 (2.6%)
    - FILE_DATE non-missing: 13,431 (100.0%) [2006-2022]- *OK* 
    - PERMIT_DATE non-missing: 209 (1.6%) [2006-2022]- **FAIL** 
    - FINAL_DATE non-missing: 2,960 (22.0%) [2006-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 13,431 (100.0%) [2006-2022]- *OK*



## Fresno, CA

- Total permits: 531,964
- STATUS_NORMALIZED not missing: 528,357 (99.3%) - *OK*
  - Active: 76,637 (14.5%)
    - FILE_DATE non-missing: 76,637 (100.0%) [2000-2022]- *OK* 
    - PERMIT_DATE non-missing: 75,599 (98.6%) [2005-2022]- *OK* 
    - FINAL_DATE non-missing: 6,579 (8.6%) [2004-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 76,637 (100.0%) [2005-2022]- *OK*
  - Final: 397,437 (75.2%)
    - FILE_DATE non-missing: 397,437 (100.0%) [2000-2022]- *OK* 
    - PERMIT_DATE non-missing: 387,945 (97.6%) [2000-2022]- *OK* 
    - FINAL_DATE non-missing: 210,604 (53.0%) [2000-2022]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 397,437 (100.0%) [2000-2022]- *OK*
  - Inactive: 6,082 (1.2%)
    - FILE_DATE non-missing: 6,082 (100.0%) [2000-2022]- *OK* 
    - PERMIT_DATE non-missing: 2,608 (42.9%) [2000-2021]- **FAIL** 
    - FINAL_DATE non-missing: 1,208 (19.9%) [2000-2018]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 6,082 (100.0%) [2000-2022]- *OK*
  - In Review: 48,201 (9.1%)
    - FILE_DATE non-missing: 48,201 (100.0%) [2000-2023]- *OK* 
    - PERMIT_DATE non-missing: 24,308 (50.4%) [2009-2018]- **FAIL** 
    - FINAL_DATE non-missing: 250 (0.5%) [2001-2021]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 48,201 (100.0%) [2009-2023]- *OK*



## Sacramento, CA

- Total permits: 512,188
- STATUS_NORMALIZED not missing: 512,051 (100.0%) - *OK*
  - Active: 36,422 (7.1%)
    - FILE_DATE non-missing: 36,422 (100.0%) [2005-2025]- *OK* 
    - PERMIT_DATE non-missing: 30,691 (84.3%) [2008-2025]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 36,422 (100.0%) [2005-2025]- *OK*
  - Final: 354,558 (69.2%)
    - FILE_DATE non-missing: 354,558 (100.0%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 217,112 (61.2%) [2007-2024]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 354,558 (100.0%) [2000-2025]- *OK*
  - Inactive: 92,954 (18.2%)
    - FILE_DATE non-missing: 92,954 (100.0%) [2000-2023]- *OK* 
    - PERMIT_DATE non-missing: 57,339 (61.7%) [2007-2022]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 92,954 (100.0%) [2000-2023]- *OK*
  - In Review: 28,117 (5.5%)
    - FILE_DATE non-missing: 28,117 (100.0%) [2008-2025]- *OK* 
    - PERMIT_DATE non-missing: 4 (0.0%) [2020-2024]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 28,117 (100.0%) [2008-2025]- *OK*



## Mesa, AZ

- Total permits: 318,153
- STATUS_NORMALIZED not missing: 308,906 (97.1%) - *OK*
  - Active: 55,252 (17.9%)
    - FILE_DATE non-missing: 55,252 (100.0%) [2017-2025]- *OK* 
    - PERMIT_DATE non-missing: 19,314 (35.0%) [2017-2025]- **FAIL** 
    - FINAL_DATE non-missing: 39 (0.1%) [2018-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 55,252 (100.0%) [2017-2025]- *OK*
  - Final: 187,580 (60.7%)
    - FILE_DATE non-missing: 187,580 (100.0%) [2017-2025]- *OK* 
    - PERMIT_DATE non-missing: 85,175 (45.4%) [2017-2025]- **FAIL** 
    - FINAL_DATE non-missing: 57,281 (30.5%) [2017-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 187,580 (100.0%) [2017-2025]- *OK*
  - Inactive: 19,656 (6.4%)
    - FILE_DATE non-missing: 19,656 (100.0%) [2015-2025]- *OK* 
    - PERMIT_DATE non-missing: 5,352 (27.2%) [2017-2025]- **FAIL** 
    - FINAL_DATE non-missing: 34 (0.2%) [2018-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 19,656 (100.0%) [2015-2025]- *OK*
  - In Review: 46,418 (15.0%)
    - FILE_DATE non-missing: 46,418 (100.0%) [2018-2025]- *OK* 
    - PERMIT_DATE non-missing: 390 (0.8%) [2018-2025]- **FAIL** 
    - FINAL_DATE non-missing: 21 (0.0%) [2021-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 46,418 (100.0%) [2018-2025]- *OK*



## Kansas City, MO

- Total permits: 690,985
- STATUS_NORMALIZED not missing: 690,136 (99.9%) - *OK*
  - Active: 216,344 (31.3%)
    - FILE_DATE non-missing: 216,344 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 214,018 (98.9%) [2010-2025]- *OK* 
    - FINAL_DATE non-missing: 892 (0.4%) [2009-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 216,344 (100.0%) [2010-2025]- *OK*
  - Final: 374,007 (54.2%)
    - FILE_DATE non-missing: 374,007 (100.0%) [2009-2024]- *OK* 
    - PERMIT_DATE non-missing: 371,185 (99.2%) [2009-2024]- *OK* 
    - FINAL_DATE non-missing: 354,918 (94.9%) [2010-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 374,007 (100.0%) [2009-2024]- *OK*
  - Inactive: 69,956 (10.1%)
    - FILE_DATE non-missing: 69,956 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 45,590 (65.2%) [2010-2024]- **FAIL** 
    - FINAL_DATE non-missing: 59,133 (84.5%) [2012-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 69,956 (100.0%) [2010-2025]- *OK*
  - In Review: 29,829 (4.3%)
    - FILE_DATE non-missing: 29,829 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 13,185 (44.2%) [2009-2025]- **FAIL** 
    - FINAL_DATE non-missing: 11,777 (39.5%) [2010-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 29,829 (100.0%) [2010-2025]- *OK*



## Atlanta, GA

- Total permits: 1,366,047
- STATUS_NORMALIZED not missing: 1,296,578 (94.9%) - *OK*
  - Active: 501,247 (38.7%)
    - FILE_DATE non-missing: 501,247 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 482,213 (96.2%) [2010-2025]- *OK* 
    - FINAL_DATE non-missing: 74,527 (14.9%) [2010-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 501,247 (100.0%) [2010-2025]- *OK*
  - Final: 409,149 (31.6%)
    - FILE_DATE non-missing: 409,148 (100.0%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 74,910 (18.3%) [2010-2024]- **FAIL** 
    - FINAL_DATE non-missing: 9,599 (2.3%) [2013-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 409,148 (100.0%) [2000-2025]- *OK*
  - Inactive: 23,929 (1.8%)
    - FILE_DATE non-missing: 23,763 (99.3%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 2,658 (11.1%) [2010-2024]- **FAIL** 
    - FINAL_DATE non-missing: 115 (0.5%) [2013-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 23,763 (99.3%) [2000-2025]- *OK*
  - In Review: 362,253 (27.9%)
    - FILE_DATE non-missing: 362,240 (100.0%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 8,297 (2.3%) [2011-2025]- **FAIL** 
    - FINAL_DATE non-missing: 675 (0.2%) [2015-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 362,240 (100.0%) [2000-2025]- *OK*



## Omaha, NE

- Total permits: 977,079
- STATUS_NORMALIZED not missing: 950,802 (97.3%) - *OK*
  - Active: 700,052 (73.6%)
    - FILE_DATE non-missing: 700,052 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 664,423 (94.9%) [2010-2025]- *OK* 
    - FINAL_DATE non-missing: 1,336 (0.2%) [2010-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 700,052 (100.0%) [2010-2025]- *OK*
  - Final: 186,447 (19.6%)
    - FILE_DATE non-missing: 186,447 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 68,319 (36.6%) [2011-2025]- **FAIL** 
    - FINAL_DATE non-missing: 63,760 (34.2%) [2011-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 186,447 (100.0%) [2010-2025]- *OK*
  - Inactive: 27,857 (2.9%)
    - FILE_DATE non-missing: 27,857 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 6,350 (22.8%) [2010-2025]- **FAIL** 
    - FINAL_DATE non-missing: 30 (0.1%) [2011-2023]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 27,857 (100.0%) [2010-2025]- *OK*
  - In Review: 36,446 (3.8%)
    - FILE_DATE non-missing: 36,446 (100.0%) [2011-2025]- *OK* 
    - PERMIT_DATE non-missing: 207 (0.6%) [2010-2025]- **FAIL** 
    - FINAL_DATE non-missing: 74 (0.2%) [2010-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 36,446 (100.0%) [2011-2025]- *OK*



## Colorado Springs, CO

*Note: The best match for Colorado Springs, CO in the permits data was El Paso County, CO*.

- Total permits: 1,420,309
- STATUS_NORMALIZED not missing: 1,400,194 (98.6%) - *OK*
  - Active: 0 (0.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - Final: 1,299,358 (92.8%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 1,299,358 (100.0%) [1985-2024]- *OK* 
    - FINAL_DATE non-missing: 1,283,734 (98.8%) [1985-2025]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 1,299,358 (100.0%) [1985-2024]- *OK*
  - Inactive: 84,175 (6.0%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 84,175 (100.0%) [1983-2022]- *OK* 
    - FINAL_DATE non-missing: 30,469 (36.2%) [1983-2018]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 84,175 (100.0%) [1983-2022]- *OK*
  - In Review: 16,661 (1.2%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 16,661 (100.0%) [1988-2025]- *OK* 
    - FINAL_DATE non-missing: 8,277 (49.7%) [1988-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 16,661 (100.0%) [1988-2025]- *OK*



## Raleigh, NC

- Total permits: 986,819
- STATUS_NORMALIZED not missing: 986,593 (100.0%) - *OK*
  - Active: 165,156 (16.7%)
    - FILE_DATE non-missing: 165,156 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 165,112 (100.0%) [2010-2025]- *OK* 
    - FINAL_DATE non-missing: 572 (0.3%) [2017-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 165,156 (100.0%) [2010-2025]- *OK*
  - Final: 670,774 (68.0%)
    - FILE_DATE non-missing: 670,774 (100.0%) [2009-2024]- *OK* 
    - PERMIT_DATE non-missing: 668,178 (99.6%) [2009-2024]- *OK* 
    - FINAL_DATE non-missing: 670,641 (100.0%) [2010-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 670,774 (100.0%) [2009-2024]- *OK*
  - Inactive: 86,544 (8.8%)
    - FILE_DATE non-missing: 86,544 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 72,823 (84.1%) [2009-2023]- **FAIL** 
    - FINAL_DATE non-missing: 65,558 (75.8%) [2009-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 86,544 (100.0%) [2010-2025]- *OK*
  - In Review: 64,119 (6.5%)
    - FILE_DATE non-missing: 64,119 (100.0%) [2018-2025]- *OK* 
    - PERMIT_DATE non-missing: 248 (0.4%) [2012-2025]- **FAIL** 
    - FINAL_DATE non-missing: 93 (0.1%) [2018-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 64,119 (100.0%) [2018-2025]- *OK*



## Long Beach, CA

- Total permits: 390,390
- STATUS_NORMALIZED not missing: 214,020 (54.8%) - **FAIL**
  - Active: 23,860 (11.1%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 22,693 (95.1%) [2009-2025]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - Final: 147,473 (68.9%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 146,146 (99.1%) [2009-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - Inactive: 27,586 (12.9%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 23,590 (85.5%) [2010-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**
  - In Review: 15,101 (7.1%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - FINAL_DATE non-missing: 13,779 (91.2%) [2009-2025]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL**



## Virginia Beach, VA

- Total permits: 621,138
- STATUS_NORMALIZED not missing: 612,365 (98.6%) - *OK*
  - Active: 85,462 (14.0%)
    - FILE_DATE non-missing: 85,462 (100.0%) [2011-2025]- *OK* 
    - PERMIT_DATE non-missing: 68,058 (79.6%) [2012-2025]- **FAIL** 
    - FINAL_DATE non-missing: 248 (0.3%) [2012-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 85,462 (100.0%) [2011-2025]- *OK*
  - Final: 487,678 (79.6%)
    - FILE_DATE non-missing: 487,678 (100.0%) [2009-2025]- *OK* 
    - PERMIT_DATE non-missing: 409,640 (84.0%) [2009-2025]- **FAIL** 
    - FINAL_DATE non-missing: 342,552 (70.2%) [2010-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 487,678 (100.0%) [2009-2025]- *OK*
  - Inactive: 19,229 (3.1%)
    - FILE_DATE non-missing: 19,229 (100.0%) [2010-2025]- *OK* 
    - PERMIT_DATE non-missing: 3,699 (19.2%) [2009-2025]- **FAIL** 
    - FINAL_DATE non-missing: 851 (4.4%) [2009-2014]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 19,229 (100.0%) [2010-2025]- *OK*
  - In Review: 19,996 (3.3%)
    - FILE_DATE non-missing: 19,996 (100.0%) [2013-2025]- *OK* 
    - PERMIT_DATE non-missing: 1,620 (8.1%) [2015-2025]- **FAIL** 
    - FINAL_DATE non-missing: 35 (0.2%) [2012-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 19,996 (100.0%) [2013-2025]- *OK*



## Miami, FL

- Total permits: 251,842
- STATUS_NORMALIZED not missing: 251,842 (100.0%) - *OK*
  - Active: 44,800 (17.8%)
    - FILE_DATE non-missing: 4,303 (9.6%) [2012-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 44,800 (100.0%) [2015-2025]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 44,800 (100.0%) [2015-2025]- *OK*
  - Final: 190,821 (75.8%)
    - FILE_DATE non-missing: 44,557 (23.4%) [2012-2022]- **FAIL** 
    - PERMIT_DATE non-missing: 190,820 (100.0%) [2015-2025]- *OK* 
    - FINAL_DATE non-missing: 190,821 (100.0%) [2019-2025]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 190,821 (100.0%) [2015-2025]- *OK*
  - Inactive: 15,430 (6.1%)
    - FILE_DATE non-missing: 6,301 (40.8%) [2012-2023]- **FAIL** 
    - PERMIT_DATE non-missing: 15,412 (99.9%) [2012-2024]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 15,423 (100.0%) [2012-2024]- *OK*
  - In Review: 791 (0.3%)
    - FILE_DATE non-missing: 300 (37.9%) [2013-2022]- **FAIL** 
    - PERMIT_DATE non-missing: 783 (99.0%) [2013-2025]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 784 (99.1%) [2013-2025]- *OK*



## Oakland, CA

- Total permits: 756,860
- STATUS_NORMALIZED not missing: 720,059 (95.1%) - *OK*
  - Active: 126,465 (17.6%)
    - FILE_DATE non-missing: 126,465 (100.0%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 29,336 (23.2%) [2015-2025]- **FAIL** 
    - FINAL_DATE non-missing: 453 (0.4%) [2014-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 126,465 (100.0%) [2000-2025]- *OK*
  - Final: 346,783 (48.2%)
    - FILE_DATE non-missing: 346,783 (100.0%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 134,143 (38.7%) [2014-2025]- **FAIL** 
    - FINAL_DATE non-missing: 105,928 (30.5%) [2014-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 346,783 (100.0%) [2000-2025]- *OK*
  - Inactive: 194,876 (27.1%)
    - FILE_DATE non-missing: 194,876 (100.0%) [2000-2024]- *OK* 
    - PERMIT_DATE non-missing: 64,531 (33.1%) [2014-2024]- **FAIL** 
    - FINAL_DATE non-missing: 1,589 (0.8%) [2014-2023]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 194,876 (100.0%) [2000-2024]- *OK*
  - In Review: 51,935 (7.2%)
    - FILE_DATE non-missing: 51,935 (100.0%) [2000-2025]- *OK* 
    - PERMIT_DATE non-missing: 1,077 (2.1%) [2015-2025]- **FAIL** 
    - FINAL_DATE non-missing: 21 (0.0%) [2006-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 51,935 (100.0%) [2000-2025]- *OK*



## Minneapolis, MN

- Total permits: 309,903
- STATUS_NORMALIZED not missing: 309,903 (100.0%) - *OK*
  - Active: 50,277 (16.2%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 50,277 (100.0%) [2021-2025]- *OK* 
    - FINAL_DATE non-missing: 33 (0.1%) [2020-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 50,277 (100.0%) [2021-2025]- *OK*
  - Final: 231,550 (74.7%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 231,550 (100.0%) [2017-2025]- *OK* 
    - FINAL_DATE non-missing: 231,522 (100.0%) [2017-2025]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 231,550 (100.0%) [2017-2025]- *OK*
  - Inactive: 5,344 (1.7%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 5,344 (100.0%) [2016-2025]- *OK* 
    - FINAL_DATE non-missing: 1,311 (24.5%) [2019-2023]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 5,344 (100.0%) [2016-2025]- *OK*
  - In Review: 22,732 (7.3%)
    - FILE_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_DATE non-missing: 22,732 (100.0%) [2021-2025]- *OK* 
    - FINAL_DATE non-missing: 30 (0.1%) [2019-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 22,732 (100.0%) [2021-2025]- *OK*



## Tulsa, OK

- Total permits: 223,624
- STATUS_NORMALIZED not missing: 223,624 (100.0%) - *OK*
  - Active: 32,728 (14.6%)
    - FILE_DATE non-missing: 32,728 (100.0%) [2018-2025]- *OK* 
    - PERMIT_DATE non-missing: 32,724 (100.0%) [2018-2025]- *OK* 
    - FINAL_DATE non-missing: 4,598 (14.0%) [2018-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 32,728 (100.0%) [2018-2025]- *OK*
  - Final: 143,246 (64.1%)
    - FILE_DATE non-missing: 143,246 (100.0%) [2018-2025]- *OK* 
    - PERMIT_DATE non-missing: 139,145 (97.1%) [2018-2025]- *OK* 
    - FINAL_DATE non-missing: 143,169 (99.9%) [2018-2025]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 143,246 (100.0%) [2018-2025]- *OK*
  - Inactive: 36,391 (16.3%)
    - FILE_DATE non-missing: 36,391 (100.0%) [2018-2025]- *OK* 
    - PERMIT_DATE non-missing: 27,442 (75.4%) [2018-2025]- **FAIL** 
    - FINAL_DATE non-missing: 13,092 (36.0%) [2019-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 36,391 (100.0%) [2018-2025]- *OK*
  - In Review: 11,259 (5.0%)
    - FILE_DATE non-missing: 11,259 (100.0%) [2019-2025]- *OK* 
    - PERMIT_DATE non-missing: 2,836 (25.2%) [2018-2025]- **FAIL** 
    - FINAL_DATE non-missing: 46 (0.4%) [2019-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 11,259 (100.0%) [2019-2025]- *OK*



## Bakersfield, CA

- Total permits: 206,824
- STATUS_NORMALIZED not missing: 204,653 (99.0%) - *OK*
  - Active: 45,579 (22.3%)
    - FILE_DATE non-missing: 45,579 (100.0%) [2010-2024]- *OK* 
    - PERMIT_DATE non-missing: 45,579 (100.0%) [2010-2024]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 45,579 (100.0%) [2010-2024]- *OK*
  - Final: 145,570 (71.1%)
    - FILE_DATE non-missing: 145,569 (100.0%) [1991-2023]- *OK* 
    - PERMIT_DATE non-missing: 145,570 (100.0%) [1991-2024]- *OK* 
    - FINAL_DATE non-missing: 142,996 (98.2%) [1992-2024]- *OK* 
    - PERMIT_OR_FILE_DATE non-missing: 145,570 (100.0%) [1991-2024]- *OK*
  - Inactive: 3,211 (1.6%)
    - FILE_DATE non-missing: 3,210 (100.0%) [1991-2023]- *OK* 
    - PERMIT_DATE non-missing: 3,211 (100.0%) [1991-2024]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 3,211 (100.0%) [1991-2024]- *OK*
  - In Review: 10,293 (5.0%)
    - FILE_DATE non-missing: 10,293 (100.0%) [1991-2024]- *OK* 
    - PERMIT_DATE non-missing: 10,293 (100.0%) [1991-2024]- *OK* 
    - FINAL_DATE non-missing: 0 (0.0%) [nan-nan]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 10,293 (100.0%) [1991-2024]- *OK*



## Wichita, KS

**No permits data found for Wichita, KS**.

## Arlington, TX

- Total permits: 178,385
- STATUS_NORMALIZED not missing: 178,382 (100.0%) - *OK*
  - Active: 89,089 (49.9%)
    - FILE_DATE non-missing: 81,307 (91.3%) [2017-2025]- *OK* 
    - PERMIT_DATE non-missing: 89,048 (100.0%) [2017-2025]- *OK* 
    - FINAL_DATE non-missing: 22,295 (25.0%) [2022-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 89,089 (100.0%) [2017-2025]- *OK*
  - Final: 80,945 (45.4%)
    - FILE_DATE non-missing: 67,561 (83.5%) [2017-2023]- **FAIL** 
    - PERMIT_DATE non-missing: 80,945 (100.0%) [2017-2023]- *OK* 
    - FINAL_DATE non-missing: 13,369 (16.5%) [2018-2021]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 80,945 (100.0%) [2017-2023]- *OK*
  - Inactive: 8,330 (4.7%)
    - FILE_DATE non-missing: 1,668 (20.0%) [2019-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 8,330 (100.0%) [2018-2025]- *OK* 
    - FINAL_DATE non-missing: 1,341 (16.1%) [2018-2025]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 8,330 (100.0%) [2018-2025]- *OK*
  - In Review: 18 (0.0%)
    - FILE_DATE non-missing: 10 (55.6%) [2022-2025]- **FAIL** 
    - PERMIT_DATE non-missing: 18 (100.0%) [2020-2025]- *OK* 
    - FINAL_DATE non-missing: 1 (5.6%) [2024-2024]- **FAIL** 
    - PERMIT_OR_FILE_DATE non-missing: 18 (100.0%) [2020-2025]- *OK*



## By data requirements

- Require FILE_DATE for all statuses, PERMIT_DATE for all but 'In Review', FINAL_DATE for 'Final': 6 / 50 
- Require FILE_OR_PERMIT_DATE for all statuses, and FINAL_DATE for 'Final': 16 / 50 
- Require FILE_OR_PERMIT_DATE for all statuses: 41 / 50



## Conclusion

- PERMIT_OR_FILE_DATE appears mostly usable. 
- FINAL_DATE appears usable only for some jurisdictions. 
- Need to investigate:
  - If and when PERMIT_DATE and FILE_DATE are interchangeable
  - If and when FINAL_DATE is available
  - Why certain dates are not available for certain jurisdictions

