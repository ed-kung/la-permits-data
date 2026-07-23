# Building Permits Data Usability Report

For the top 50 US cities by population, random sample of 2000 permits per city.  The top 50 cities are:

['New York', 'Los Angeles', 'Chicago', 'Houston', 'Phoenix', 'Philadelphia', 'San Antonio', 'San Diego', 'Dallas', 'Jacksonville', 'Austin', 'Fort Worth', 'San Jose', 'Columbus', 'Charlotte', 'Indianapolis', 'San Francisco', 'Seattle', 'Denver', 'Oklahoma City', 'Nashville', 'Washington', 'El Paso', 'Las Vegas', 'Boston', 'Detroit', 'Portland', 'Louisville', 'Memphis', 'Baltimore', 'Milwaukee', 'Albuquerque', 'Tucson', 'Fresno', 'Sacramento', 'Mesa', 'Kansas City', 'Atlanta', 'Omaha', 'Colorado Springs', 'Raleigh', 'Long Beach', 'Virginia Beach', 'Miami', 'Oakland', 'Minneapolis', 'Tulsa', 'Bakersfield', 'Wichita', 'Arlington']

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

Geographic matching notes:

- The closest match for Las Vegas is "North Las Vegas"
- The closest match for Louisville is "Louisville-Jefferson County"
- The closest match for Colorado Springs is "El Paso County"
- There does not appear to be a match for Wichita, KS



## New York NY

- Total records: 2,000
- Schemas: 
  - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,593 (79.6%)  **FAIL**
  - Active: 569 (35.7%)
    - FILE_DATE: 569 (100.0%)  *OK*
    - PERMIT_DATE: 321 (56.4%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 569 (100.0%)  *OK*
  - Final: 882 (55.4%)
    - FILE_DATE: 882 (100.0%)  *OK*
    - PERMIT_DATE: 804 (91.2%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 882 (100.0%)  *OK*
  - Inactive: 56 (3.5%)
    - FILE_DATE: 54 (96.4%)  *OK*
    - PERMIT_DATE: 4 (7.1%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 54 (96.4%)  *OK*
  - In Review: 86 (5.4%)
    - FILE_DATE: 86 (100.0%)  *OK*
    - PERMIT_DATE: 3 (3.5%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 86 (100.0%)  *OK*



## Los Angeles CA

- Total records: 2,002
- Schemas: 
  - custom: 2,002 (100.0%)
- STATUS_NORMALIZED not missing: 1,869 (93.4%)  *OK*
  - Active: 251 (13.4%)
    - FILE_DATE: 54 (21.5%)  **FAIL**
    - PERMIT_DATE: 251 (100.0%)  *OK*
    - FINAL_DATE: 2 (0.8%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 251 (100.0%)  *OK*
  - Final: 1,300 (69.6%)
    - FILE_DATE: 338 (26.0%)  **FAIL**
    - PERMIT_DATE: 1,299 (99.9%)  *OK*
    - FINAL_DATE: 1,264 (97.2%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,299 (99.9%)  *OK*
  - Inactive: 140 (7.5%)
    - FILE_DATE: 33 (23.6%)  **FAIL**
    - PERMIT_DATE: 131 (93.6%)  *OK*
    - FINAL_DATE: 3 (2.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 140 (100.0%)  *OK*
  - In Review: 178 (9.5%)
    - FILE_DATE: 167 (93.8%)  *OK*
    - PERMIT_DATE: 4 (2.2%)  **FAIL**
    - FINAL_DATE: 2 (1.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 168 (94.4%)  *OK*



## Chicago IL

- Total records: 1,998
- Schemas: 
  - custom: 1,998 (100.0%)
- STATUS_NORMALIZED not missing: 0 (0.0%)  **FAIL**
  - Active: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - Final: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - Inactive: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - In Review: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**



## Houston TX

- Total records: 2,001
- Schemas: 
  - custom: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 2,001 (100.0%)  *OK*
  - Active: 2,001 (100.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 1,976 (98.8%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,976 (98.8%)  *OK*
  - Final: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - Inactive: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - In Review: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**



## Phoenix AZ

- Total records: 1,992
- Schemas: 
  - custom: 1,992 (100.0%)
- STATUS_NORMALIZED not missing: 1,917 (96.2%)  *OK*
  - Active: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - Final: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - Inactive: 438 (22.8%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 386 (88.1%)  *OK*
    - FINAL_DATE: 123 (28.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 386 (88.1%)  *OK*
  - In Review: 1,479 (77.2%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 1,337 (90.4%)  *OK*
    - FINAL_DATE: 1,190 (80.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,337 (90.4%)  *OK*



## Philadelphia PA

- Total records: 1,998
- Schemas: 
  - custom: 1,998 (100.0%)
- STATUS_NORMALIZED not missing: 1,927 (96.4%)  *OK*
  - Active: 244 (12.7%)
    - FILE_DATE: 95 (38.9%)  **FAIL**
    - PERMIT_DATE: 243 (99.6%)  *OK*
    - FINAL_DATE: 4 (1.6%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 243 (99.6%)  *OK*
  - Final: 1,485 (77.1%)
    - FILE_DATE: 205 (13.8%)  **FAIL**
    - PERMIT_DATE: 1,485 (100.0%)  *OK*
    - FINAL_DATE: 1,448 (97.5%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,485 (100.0%)  *OK*
  - Inactive: 191 (9.9%)
    - FILE_DATE: 46 (24.1%)  **FAIL**
    - PERMIT_DATE: 189 (99.0%)  *OK*
    - FINAL_DATE: 151 (79.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 190 (99.5%)  *OK*
  - In Review: 7 (0.4%)
    - FILE_DATE: 7 (100.0%)  *OK*
    - PERMIT_DATE: 1 (14.3%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 7 (100.0%)  *OK*



## San Antonio TX

- Total records: 2,002
- Schemas: 
  - accela: 2,000 (99.9%)
  - custom: 2 (0.1%)
- STATUS_NORMALIZED not missing: 1,950 (97.4%)  *OK*
  - Active: 824 (42.3%)
    - FILE_DATE: 816 (99.0%)  *OK*
    - PERMIT_DATE: 156 (18.9%)  **FAIL**
    - FINAL_DATE: 27 (3.3%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 817 (99.2%)  *OK*
  - Final: 754 (38.7%)
    - FILE_DATE: 747 (99.1%)  *OK*
    - PERMIT_DATE: 139 (18.4%)  **FAIL**
    - FINAL_DATE: 2 (0.3%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 748 (99.2%)  *OK*
  - Inactive: 251 (12.9%)
    - FILE_DATE: 250 (99.6%)  *OK*
    - PERMIT_DATE: 4 (1.6%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 250 (99.6%)  *OK*
  - In Review: 121 (6.2%)
    - FILE_DATE: 121 (100.0%)  *OK*
    - PERMIT_DATE: 1 (0.8%)  **FAIL**
    - FINAL_DATE: 3 (2.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 121 (100.0%)  *OK*



## San Diego CA

- Total records: 1,996
- Schemas: 
  - custom: 956 (47.9%)
  - accela: 1,040 (52.1%)
- STATUS_NORMALIZED not missing: 1,961 (98.2%)  *OK*
  - Active: 668 (34.1%)
    - FILE_DATE: 533 (79.8%)  **FAIL**
    - PERMIT_DATE: 535 (80.1%)  **FAIL**
    - FINAL_DATE: 6 (0.9%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 668 (100.0%)  *OK*
  - Final: 752 (38.3%)
    - FILE_DATE: 737 (98.0%)  *OK*
    - PERMIT_DATE: 736 (97.9%)  *OK*
    - FINAL_DATE: 690 (91.8%)  *OK*
    - PERMIT_OR_FILE_DATE: 752 (100.0%)  *OK*
  - Inactive: 169 (8.6%)
    - FILE_DATE: 155 (91.7%)  *OK*
    - PERMIT_DATE: 97 (57.4%)  **FAIL**
    - FINAL_DATE: 96 (56.8%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 164 (97.0%)  *OK*
  - In Review: 372 (19.0%)
    - FILE_DATE: 328 (88.2%)  *OK*
    - PERMIT_DATE: 5 (1.3%)  **FAIL**
    - FINAL_DATE: 1 (0.3%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 328 (88.2%)  *OK*



## Dallas TX

- Total records: 1,998
- Schemas: 
  - custom: 1,869 (93.5%)
  - accela: 129 (6.5%)
- STATUS_NORMALIZED not missing: 1,779 (89.0%)  *OK*
  - Active: 246 (13.8%)
    - FILE_DATE: 246 (100.0%)  *OK*
    - PERMIT_DATE: 208 (84.6%)  **FAIL**
    - FINAL_DATE: 1 (0.4%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 246 (100.0%)  *OK*
  - Final: 1,057 (59.4%)
    - FILE_DATE: 1,057 (100.0%)  *OK*
    - PERMIT_DATE: 1,025 (97.0%)  *OK*
    - FINAL_DATE: 1,033 (97.7%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,057 (100.0%)  *OK*
  - Inactive: 374 (21.0%)
    - FILE_DATE: 374 (100.0%)  *OK*
    - PERMIT_DATE: 148 (39.6%)  **FAIL**
    - FINAL_DATE: 369 (98.7%)  *OK*
    - PERMIT_OR_FILE_DATE: 374 (100.0%)  *OK*
  - In Review: 102 (5.7%)
    - FILE_DATE: 102 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 102 (100.0%)  *OK*



## Jacksonville FL

- Total records: 1,995
- Schemas: 
  - custom: 1,995 (100.0%)
- STATUS_NORMALIZED not missing: 1,440 (72.2%)  **FAIL**
  - Active: 25 (1.7%)
    - FILE_DATE: 22 (88.0%)  *OK*
    - PERMIT_DATE: 25 (100.0%)  *OK*
    - FINAL_DATE: 1 (4.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 25 (100.0%)  *OK*
  - Final: 1,302 (90.4%)
    - FILE_DATE: 241 (18.5%)  **FAIL**
    - PERMIT_DATE: 1,301 (99.9%)  *OK*
    - FINAL_DATE: 241 (18.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,301 (99.9%)  *OK*
  - Inactive: 108 (7.5%)
    - FILE_DATE: 9 (8.3%)  **FAIL**
    - PERMIT_DATE: 35 (32.4%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 35 (32.4%)  **FAIL**
  - In Review: 5 (0.3%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 4 (80.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 4 (80.0%)  **FAIL**



## Austin TX

- Total records: 1,990
- Schemas: 
  - custom: 1,990 (100.0%)
- STATUS_NORMALIZED not missing: 1,990 (100.0%)  *OK*
  - Active: 52 (2.6%)
    - FILE_DATE: 50 (96.2%)  *OK*
    - PERMIT_DATE: 50 (96.2%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 50 (96.2%)  *OK*
  - Final: 1,643 (82.6%)
    - FILE_DATE: 1,643 (100.0%)  *OK*
    - PERMIT_DATE: 1,643 (100.0%)  *OK*
    - FINAL_DATE: 1,643 (100.0%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,643 (100.0%)  *OK*
  - Inactive: 295 (14.8%)
    - FILE_DATE: 295 (100.0%)  *OK*
    - PERMIT_DATE: 295 (100.0%)  *OK*
    - FINAL_DATE: 158 (53.6%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 295 (100.0%)  *OK*
  - In Review: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**



## Fort Worth TX

- Total records: 1,996
- Schemas: 
  - accela: 1,966 (98.5%)
  - custom: 30 (1.5%)
- STATUS_NORMALIZED not missing: 1,990 (99.7%)  *OK*
  - Active: 241 (12.1%)
    - FILE_DATE: 241 (100.0%)  *OK*
    - PERMIT_DATE: 225 (93.4%)  *OK*
    - FINAL_DATE: 3 (1.2%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 241 (100.0%)  *OK*
  - Final: 1,271 (63.9%)
    - FILE_DATE: 1,271 (100.0%)  *OK*
    - PERMIT_DATE: 1,262 (99.3%)  *OK*
    - FINAL_DATE: 759 (59.7%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,271 (100.0%)  *OK*
  - Inactive: 444 (22.3%)
    - FILE_DATE: 444 (100.0%)  *OK*
    - PERMIT_DATE: 234 (52.7%)  **FAIL**
    - FINAL_DATE: 5 (1.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 444 (100.0%)  *OK*
  - In Review: 34 (1.7%)
    - FILE_DATE: 34 (100.0%)  *OK*
    - PERMIT_DATE: 2 (5.9%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 34 (100.0%)  *OK*



## San Jose CA

- Total records: 1,997
- Schemas: 
  - custom: 1,997 (100.0%)
- STATUS_NORMALIZED not missing: 1,997 (100.0%)  *OK*
  - Active: 375 (18.8%)
    - FILE_DATE: 374 (99.7%)  *OK*
    - PERMIT_DATE: 326 (86.9%)  *OK*
    - FINAL_DATE: 4 (1.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 375 (100.0%)  *OK*
  - Final: 971 (48.6%)
    - FILE_DATE: 967 (99.6%)  *OK*
    - PERMIT_DATE: 807 (83.1%)  **FAIL**
    - FINAL_DATE: 270 (27.8%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 969 (99.8%)  *OK*
  - Inactive: 357 (17.9%)
    - FILE_DATE: 356 (99.7%)  *OK*
    - PERMIT_DATE: 196 (54.9%)  **FAIL**
    - FINAL_DATE: 3 (0.8%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 356 (99.7%)  *OK*
  - In Review: 294 (14.7%)
    - FILE_DATE: 293 (99.7%)  *OK*
    - PERMIT_DATE: 49 (16.7%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 293 (99.7%)  *OK*



## Columbus OH

- Total records: 1,993
- Schemas: 
  - accela: 1,968 (98.7%)
  - custom: 25 (1.3%)
- STATUS_NORMALIZED not missing: 1,695 (85.0%)  *OK*
  - Active: 356 (21.0%)
    - FILE_DATE: 356 (100.0%)  *OK*
    - PERMIT_DATE: 331 (93.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 356 (100.0%)  *OK*
  - Final: 1,227 (72.4%)
    - FILE_DATE: 1,227 (100.0%)  *OK*
    - PERMIT_DATE: 906 (73.8%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,227 (100.0%)  *OK*
  - Inactive: 85 (5.0%)
    - FILE_DATE: 85 (100.0%)  *OK*
    - PERMIT_DATE: 61 (71.8%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 85 (100.0%)  *OK*
  - In Review: 27 (1.6%)
    - FILE_DATE: 27 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 27 (100.0%)  *OK*



## Charlotte NC

- Total records: 2,001
- Schemas: 
  - accela: 1,999 (99.9%)
  - custom: 2 (0.1%)
- STATUS_NORMALIZED not missing: 1,634 (81.7%)  **FAIL**
  - Active: 433 (26.5%)
    - FILE_DATE: 433 (100.0%)  *OK*
    - PERMIT_DATE: 146 (33.7%)  **FAIL**
    - FINAL_DATE: 32 (7.4%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 433 (100.0%)  *OK*
  - Final: 328 (20.1%)
    - FILE_DATE: 328 (100.0%)  *OK*
    - PERMIT_DATE: 44 (13.4%)  **FAIL**
    - FINAL_DATE: 59 (18.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 328 (100.0%)  *OK*
  - Inactive: 82 (5.0%)
    - FILE_DATE: 82 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 82 (100.0%)  *OK*
  - In Review: 791 (48.4%)
    - FILE_DATE: 791 (100.0%)  *OK*
    - PERMIT_DATE: 2 (0.3%)  **FAIL**
    - FINAL_DATE: 3 (0.4%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 791 (100.0%)  *OK*



## Indianapolis IN

- Total records: 2,001
- Schemas: 
  - accela: 1,185 (59.2%)
  - custom: 816 (40.8%)
- STATUS_NORMALIZED not missing: 1,871 (93.5%)  *OK*
  - Active: 729 (39.0%)
    - FILE_DATE: 729 (100.0%)  *OK*
    - PERMIT_DATE: 375 (51.4%)  **FAIL**
    - FINAL_DATE: 34 (4.7%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 729 (100.0%)  *OK*
  - Final: 797 (42.6%)
    - FILE_DATE: 797 (100.0%)  *OK*
    - PERMIT_DATE: 485 (60.9%)  **FAIL**
    - FINAL_DATE: 387 (48.6%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 797 (100.0%)  *OK*
  - Inactive: 73 (3.9%)
    - FILE_DATE: 73 (100.0%)  *OK*
    - PERMIT_DATE: 11 (15.1%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 73 (100.0%)  *OK*
  - In Review: 272 (14.5%)
    - FILE_DATE: 272 (100.0%)  *OK*
    - PERMIT_DATE: 3 (1.1%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 272 (100.0%)  *OK*



## San Francisco CA

- Total records: 2,001
- Schemas: 
  - custom: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 1,994 (99.7%)  *OK*
  - Active: 754 (37.8%)
    - FILE_DATE: 463 (61.4%)  **FAIL**
    - PERMIT_DATE: 754 (100.0%)  *OK*
    - FINAL_DATE: 215 (28.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 754 (100.0%)  *OK*
  - Final: 853 (42.8%)
    - FILE_DATE: 853 (100.0%)  *OK*
    - PERMIT_DATE: 853 (100.0%)  *OK*
    - FINAL_DATE: 853 (100.0%)  *OK*
    - PERMIT_OR_FILE_DATE: 853 (100.0%)  *OK*
  - Inactive: 68 (3.4%)
    - FILE_DATE: 64 (94.1%)  *OK*
    - PERMIT_DATE: 39 (57.4%)  **FAIL**
    - FINAL_DATE: 1 (1.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 64 (94.1%)  *OK*
  - In Review: 319 (16.0%)
    - FILE_DATE: 319 (100.0%)  *OK*
    - PERMIT_DATE: 210 (65.8%)  **FAIL**
    - FINAL_DATE: 167 (52.4%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 319 (100.0%)  *OK*



## Seattle WA

- Total records: 2,002
- Schemas: 
  - accela: 1,717 (85.8%)
  - custom: 285 (14.2%)
- STATUS_NORMALIZED not missing: 2,002 (100.0%)  *OK*
  - Active: 162 (8.1%)
    - FILE_DATE: 162 (100.0%)  *OK*
    - PERMIT_DATE: 155 (95.7%)  *OK*
    - FINAL_DATE: 1 (0.6%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 162 (100.0%)  *OK*
  - Final: 1,610 (80.4%)
    - FILE_DATE: 1,610 (100.0%)  *OK*
    - PERMIT_DATE: 345 (21.4%)  **FAIL**
    - FINAL_DATE: 322 (20.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,610 (100.0%)  *OK*
  - Inactive: 120 (6.0%)
    - FILE_DATE: 120 (100.0%)  *OK*
    - PERMIT_DATE: 35 (29.2%)  **FAIL**
    - FINAL_DATE: 1 (0.8%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 120 (100.0%)  *OK*
  - In Review: 110 (5.5%)
    - FILE_DATE: 110 (100.0%)  *OK*
    - PERMIT_DATE: 4 (3.6%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 110 (100.0%)  *OK*



## Denver CO

- Total records: 1,998
- Schemas: 
  - accela: 1,522 (76.2%)
  - custom: 476 (23.8%)
- STATUS_NORMALIZED not missing: 1,994 (99.8%)  *OK*
  - Active: 153 (7.7%)
    - FILE_DATE: 146 (95.4%)  *OK*
    - PERMIT_DATE: 152 (99.3%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 153 (100.0%)  *OK*
  - Final: 1,554 (77.9%)
    - FILE_DATE: 1,547 (99.5%)  *OK*
    - PERMIT_DATE: 1,063 (68.4%)  **FAIL**
    - FINAL_DATE: 15 (1.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,552 (99.9%)  *OK*
  - Inactive: 146 (7.3%)
    - FILE_DATE: 146 (100.0%)  *OK*
    - PERMIT_DATE: 87 (59.6%)  **FAIL**
    - FINAL_DATE: 3 (2.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 146 (100.0%)  *OK*
  - In Review: 141 (7.1%)
    - FILE_DATE: 138 (97.9%)  *OK*
    - PERMIT_DATE: 3 (2.1%)  **FAIL**
    - FINAL_DATE: 1 (0.7%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 138 (97.9%)  *OK*



## Oklahoma City OK

- Total records: 1,996
- Schemas: 
  - accela: 1,985 (99.4%)
  - custom: 11 (0.6%)
- STATUS_NORMALIZED not missing: 1,690 (84.7%)  **FAIL**
  - Active: 165 (9.8%)
    - FILE_DATE: 165 (100.0%)  *OK*
    - PERMIT_DATE: 143 (86.7%)  *OK*
    - FINAL_DATE: 7 (4.2%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 165 (100.0%)  *OK*
  - Final: 1,507 (89.2%)
    - FILE_DATE: 1,507 (100.0%)  *OK*
    - PERMIT_DATE: 1,219 (80.9%)  **FAIL**
    - FINAL_DATE: 1,086 (72.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,507 (100.0%)  *OK*
  - Inactive: 8 (0.5%)
    - FILE_DATE: 8 (100.0%)  *OK*
    - PERMIT_DATE: 2 (25.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 8 (100.0%)  *OK*
  - In Review: 10 (0.6%)
    - FILE_DATE: 10 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 10 (100.0%)  *OK*



## Nashville TN

- Total records: 1,996
- Schemas: 
  - custom: 1,978 (99.1%)
  - nan: 0 (0.0%)
- STATUS_NORMALIZED not missing: 1,993 (99.8%)  *OK*
  - Active: 276 (13.8%)
    - FILE_DATE: 274 (99.3%)  *OK*
    - PERMIT_DATE: 274 (99.3%)  *OK*
    - FINAL_DATE: 1 (0.4%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 274 (99.3%)  *OK*
  - Final: 50 (2.5%)
    - FILE_DATE: 49 (98.0%)  *OK*
    - PERMIT_DATE: 49 (98.0%)  *OK*
    - FINAL_DATE: 4 (8.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 49 (98.0%)  *OK*
  - Inactive: 392 (19.7%)
    - FILE_DATE: 372 (94.9%)  *OK*
    - PERMIT_DATE: 372 (94.9%)  *OK*
    - FINAL_DATE: 191 (48.7%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 372 (94.9%)  *OK*
  - In Review: 1,275 (64.0%)
    - FILE_DATE: 1,200 (94.1%)  *OK*
    - PERMIT_DATE: 1,200 (94.1%)  *OK*
    - FINAL_DATE: 383 (30.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,200 (94.1%)  *OK*



## Washington DC

- Total records: 2,001
- Schemas: 
  - custom: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 1,999 (99.9%)  *OK*
  - Active: 1,418 (70.9%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 1,418 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,418 (100.0%)  *OK*
  - Final: 569 (28.5%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 569 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 569 (100.0%)  *OK*
  - Inactive: 6 (0.3%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 6 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 6 (100.0%)  *OK*
  - In Review: 6 (0.3%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 6 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 6 (100.0%)  *OK*



## El Paso TX

- Total records: 2,000
- Schemas: 
  - accela: 1,987 (99.3%)
  - custom: 13 (0.6%)
- STATUS_NORMALIZED not missing: 1,987 (99.3%)  *OK*
  - Active: 575 (28.9%)
    - FILE_DATE: 575 (100.0%)  *OK*
    - PERMIT_DATE: 458 (79.7%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 575 (100.0%)  *OK*
  - Final: 1,166 (58.7%)
    - FILE_DATE: 1,166 (100.0%)  *OK*
    - PERMIT_DATE: 944 (81.0%)  **FAIL**
    - FINAL_DATE: 1 (0.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,166 (100.0%)  *OK*
  - Inactive: 216 (10.9%)
    - FILE_DATE: 216 (100.0%)  *OK*
    - PERMIT_DATE: 172 (79.6%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 216 (100.0%)  *OK*
  - In Review: 30 (1.5%)
    - FILE_DATE: 30 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 30 (100.0%)  *OK*



## North Las Vegas NV

- Total records: 2,001
- Schemas: 
  - energov: 1,989 (99.4%)
  - custom: 12 (0.6%)
- STATUS_NORMALIZED not missing: 2,001 (100.0%)  *OK*
  - Active: 947 (47.3%)
    - FILE_DATE: 947 (100.0%)  *OK*
    - PERMIT_DATE: 926 (97.8%)  *OK*
    - FINAL_DATE: 1 (0.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 947 (100.0%)  *OK*
  - Final: 332 (16.6%)
    - FILE_DATE: 332 (100.0%)  *OK*
    - PERMIT_DATE: 325 (97.9%)  *OK*
    - FINAL_DATE: 332 (100.0%)  *OK*
    - PERMIT_OR_FILE_DATE: 332 (100.0%)  *OK*
  - Inactive: 593 (29.6%)
    - FILE_DATE: 593 (100.0%)  *OK*
    - PERMIT_DATE: 558 (94.1%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 593 (100.0%)  *OK*
  - In Review: 129 (6.4%)
    - FILE_DATE: 129 (100.0%)  *OK*
    - PERMIT_DATE: 13 (10.1%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 129 (100.0%)  *OK*



## Boston MA

- Total records: 2,000
- Schemas: 
  - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 2,000 (100.0%)  *OK*
  - Active: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - Final: 733 (36.6%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 733 (100.0%)  *OK*
    - FINAL_DATE: 642 (87.6%)  *OK*
    - PERMIT_OR_FILE_DATE: 733 (100.0%)  *OK*
  - Inactive: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - In Review: 1,267 (63.3%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 1,267 (100.0%)  *OK*
    - FINAL_DATE: 1,053 (83.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,267 (100.0%)  *OK*



## Detroit MI

- Total records: 2,000
- Schemas: 
  - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,767 (88.3%)  *OK*
  - Active: 1,767 (100.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 1,767 (100.0%)  *OK*
    - FINAL_DATE: 1,767 (100.0%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,767 (100.0%)  *OK*
  - Final: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - Inactive: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - In Review: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**



## Portland OR

- Total records: 2,003
- Schemas: 
  - custom: 2,003 (100.0%)
- STATUS_NORMALIZED not missing: 1,954 (97.6%)  *OK*
  - Active: 164 (8.4%)
    - FILE_DATE: 164 (100.0%)  *OK*
    - PERMIT_DATE: 159 (97.0%)  *OK*
    - FINAL_DATE: 1 (0.6%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 164 (100.0%)  *OK*
  - Final: 1,505 (77.0%)
    - FILE_DATE: 1,505 (100.0%)  *OK*
    - PERMIT_DATE: 1,383 (91.9%)  *OK*
    - FINAL_DATE: 1,426 (94.8%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,505 (100.0%)  *OK*
  - Inactive: 242 (12.4%)
    - FILE_DATE: 242 (100.0%)  *OK*
    - PERMIT_DATE: 223 (92.1%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 242 (100.0%)  *OK*
  - In Review: 43 (2.2%)
    - FILE_DATE: 43 (100.0%)  *OK*
    - PERMIT_DATE: 4 (9.3%)  **FAIL**
    - FINAL_DATE: 1 (2.3%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 43 (100.0%)  *OK*



## Louisville-Jefferson County KY

- Total records: 2,003
- Schemas: 
  - accela: 2,003 (100.0%)
- STATUS_NORMALIZED not missing: 1,998 (99.8%)  *OK*
  - Active: 232 (11.6%)
    - FILE_DATE: 232 (100.0%)  *OK*
    - PERMIT_DATE: 231 (99.6%)  *OK*
    - FINAL_DATE: 24 (10.3%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 232 (100.0%)  *OK*
  - Final: 610 (30.5%)
    - FILE_DATE: 610 (100.0%)  *OK*
    - PERMIT_DATE: 603 (98.9%)  *OK*
    - FINAL_DATE: 366 (60.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 610 (100.0%)  *OK*
  - Inactive: 1,128 (56.5%)
    - FILE_DATE: 1,128 (100.0%)  *OK*
    - PERMIT_DATE: 1,016 (90.1%)  *OK*
    - FINAL_DATE: 570 (50.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,128 (100.0%)  *OK*
  - In Review: 28 (1.4%)
    - FILE_DATE: 28 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 28 (100.0%)  *OK*



## Memphis TN

- Total records: 2,000
- Schemas: 
  - accela: 1,990 (99.5%)
  - custom: 10 (0.5%)
- STATUS_NORMALIZED not missing: 1,990 (99.5%)  *OK*
  - Active: 209 (10.5%)
    - FILE_DATE: 209 (100.0%)  *OK*
    - PERMIT_DATE: 198 (94.7%)  *OK*
    - FINAL_DATE: 1 (0.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 209 (100.0%)  *OK*
  - Final: 1,457 (73.2%)
    - FILE_DATE: 1,457 (100.0%)  *OK*
    - PERMIT_DATE: 1,343 (92.2%)  *OK*
    - FINAL_DATE: 1,339 (91.9%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,457 (100.0%)  *OK*
  - Inactive: 302 (15.2%)
    - FILE_DATE: 302 (100.0%)  *OK*
    - PERMIT_DATE: 257 (85.1%)  *OK*
    - FINAL_DATE: 1 (0.3%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 302 (100.0%)  *OK*
  - In Review: 22 (1.1%)
    - FILE_DATE: 22 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 22 (100.0%)  *OK*



## Baltimore MD

- Total records: 2,000
- Schemas: 
  - custom: 1,221 (61.0%)
  - accela: 779 (38.9%)
- STATUS_NORMALIZED not missing: 761 (38.0%)  **FAIL**
  - Active: 46 (6.0%)
    - FILE_DATE: 46 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 46 (100.0%)  *OK*
  - Final: 219 (28.8%)
    - FILE_DATE: 219 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 219 (100.0%)  *OK*
  - Inactive: 440 (57.8%)
    - FILE_DATE: 440 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 440 (100.0%)  *OK*
  - In Review: 56 (7.4%)
    - FILE_DATE: 56 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 56 (100.0%)  *OK*



## Milwaukee WI

- Total records: 2,000
- Schemas: 
  - accela: 1,998 (99.9%)
  - custom: 2 (0.1%)
- STATUS_NORMALIZED not missing: 1,818 (90.9%)  *OK*
  - Active: 253 (13.9%)
    - FILE_DATE: 245 (96.8%)  *OK*
    - PERMIT_DATE: 81 (32.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 251 (99.2%)  *OK*
  - Final: 1,270 (69.9%)
    - FILE_DATE: 1,236 (97.3%)  *OK*
    - PERMIT_DATE: 247 (19.4%)  **FAIL**
    - FINAL_DATE: 127 (10.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,266 (99.7%)  *OK*
  - Inactive: 116 (6.4%)
    - FILE_DATE: 111 (95.7%)  *OK*
    - PERMIT_DATE: 19 (16.4%)  **FAIL**
    - FINAL_DATE: 1 (0.9%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 116 (100.0%)  *OK*
  - In Review: 179 (9.8%)
    - FILE_DATE: 176 (98.3%)  *OK*
    - PERMIT_DATE: 4 (2.2%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 176 (98.3%)  *OK*



## Albuquerque NM

- Total records: 2,001
- Schemas: 
  - custom: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 991 (49.5%)  **FAIL**
  - Active: 69 (7.0%)
    - FILE_DATE: 69 (100.0%)  *OK*
    - PERMIT_DATE: 69 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 69 (100.0%)  *OK*
  - Final: 408 (41.2%)
    - FILE_DATE: 408 (100.0%)  *OK*
    - PERMIT_DATE: 408 (100.0%)  *OK*
    - FINAL_DATE: 408 (100.0%)  *OK*
    - PERMIT_OR_FILE_DATE: 408 (100.0%)  *OK*
  - Inactive: 283 (28.6%)
    - FILE_DATE: 283 (100.0%)  *OK*
    - PERMIT_DATE: 266 (94.0%)  *OK*
    - FINAL_DATE: 283 (100.0%)  *OK*
    - PERMIT_OR_FILE_DATE: 283 (100.0%)  *OK*
  - In Review: 231 (23.3%)
    - FILE_DATE: 231 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 231 (100.0%)  *OK*



## Tucson AZ

- Total records: 1,997
- Schemas: 
  - custom: 1,997 (100.0%)
- STATUS_NORMALIZED not missing: 1,558 (78.0%)  **FAIL**
  - Active: 71 (4.6%)
    - FILE_DATE: 71 (100.0%)  *OK*
    - PERMIT_DATE: 6 (8.5%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 71 (100.0%)  *OK*
  - Final: 1,069 (68.6%)
    - FILE_DATE: 1,069 (100.0%)  *OK*
    - PERMIT_DATE: 277 (25.9%)  **FAIL**
    - FINAL_DATE: 783 (73.2%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,069 (100.0%)  *OK*
  - Inactive: 381 (24.5%)
    - FILE_DATE: 339 (89.0%)  *OK*
    - PERMIT_DATE: 48 (12.6%)  **FAIL**
    - FINAL_DATE: 73 (19.2%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 341 (89.5%)  *OK*
  - In Review: 37 (2.4%)
    - FILE_DATE: 37 (100.0%)  *OK*
    - PERMIT_DATE: 1 (2.7%)  **FAIL**
    - FINAL_DATE: 6 (16.2%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 37 (100.0%)  *OK*



## Fresno CA

- Total records: 2,000
- Schemas: 
  - accela: 1,650 (82.5%)
  - custom: 350 (17.5%)
- STATUS_NORMALIZED not missing: 1,989 (99.4%)  *OK*
  - Active: 284 (14.3%)
    - FILE_DATE: 284 (100.0%)  *OK*
    - PERMIT_DATE: 284 (100.0%)  *OK*
    - FINAL_DATE: 40 (14.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 284 (100.0%)  *OK*
  - Final: 1,522 (76.5%)
    - FILE_DATE: 1,522 (100.0%)  *OK*
    - PERMIT_DATE: 1,487 (97.7%)  *OK*
    - FINAL_DATE: 815 (53.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,522 (100.0%)  *OK*
  - Inactive: 20 (1.0%)
    - FILE_DATE: 20 (100.0%)  *OK*
    - PERMIT_DATE: 4 (20.0%)  **FAIL**
    - FINAL_DATE: 1 (5.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 20 (100.0%)  *OK*
  - In Review: 163 (8.2%)
    - FILE_DATE: 163 (100.0%)  *OK*
    - PERMIT_DATE: 83 (50.9%)  **FAIL**
    - FINAL_DATE: 2 (1.2%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 163 (100.0%)  *OK*



## Sacramento CA

- Total records: 2,000
- Schemas: 
  - accela: 1,999 (99.9%)
  - custom: 1 (0.0%)
- STATUS_NORMALIZED not missing: 1,999 (99.9%)  *OK*
  - Active: 140 (7.0%)
    - FILE_DATE: 140 (100.0%)  *OK*
    - PERMIT_DATE: 121 (86.4%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 140 (100.0%)  *OK*
  - Final: 1,372 (68.6%)
    - FILE_DATE: 1,372 (100.0%)  *OK*
    - PERMIT_DATE: 844 (61.5%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,372 (100.0%)  *OK*
  - Inactive: 364 (18.2%)
    - FILE_DATE: 364 (100.0%)  *OK*
    - PERMIT_DATE: 212 (58.2%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 364 (100.0%)  *OK*
  - In Review: 123 (6.2%)
    - FILE_DATE: 123 (100.0%)  *OK*
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 123 (100.0%)  *OK*



## Mesa AZ

- Total records: 1,999
- Schemas: 
  - accela: 1,993 (99.7%)
  - custom: 6 (0.3%)
- STATUS_NORMALIZED not missing: 1,936 (96.8%)  *OK*
  - Active: 325 (16.8%)
    - FILE_DATE: 325 (100.0%)  *OK*
    - PERMIT_DATE: 104 (32.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 325 (100.0%)  *OK*
  - Final: 1,187 (61.3%)
    - FILE_DATE: 1,187 (100.0%)  *OK*
    - PERMIT_DATE: 541 (45.6%)  **FAIL**
    - FINAL_DATE: 367 (30.9%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,187 (100.0%)  *OK*
  - Inactive: 121 (6.2%)
    - FILE_DATE: 121 (100.0%)  *OK*
    - PERMIT_DATE: 34 (28.1%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 121 (100.0%)  *OK*
  - In Review: 303 (15.7%)
    - FILE_DATE: 303 (100.0%)  *OK*
    - PERMIT_DATE: 1 (0.3%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 303 (100.0%)  *OK*



## Kansas City MO

- Total records: 2,001
- Schemas: 
  - energov: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 1,999 (99.9%)  *OK*
  - Active: 679 (34.0%)
    - FILE_DATE: 679 (100.0%)  *OK*
    - PERMIT_DATE: 666 (98.1%)  *OK*
    - FINAL_DATE: 7 (1.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 679 (100.0%)  *OK*
  - Final: 1,024 (51.2%)
    - FILE_DATE: 1,024 (100.0%)  *OK*
    - PERMIT_DATE: 1,014 (99.0%)  *OK*
    - FINAL_DATE: 981 (95.8%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,024 (100.0%)  *OK*
  - Inactive: 197 (9.9%)
    - FILE_DATE: 197 (100.0%)  *OK*
    - PERMIT_DATE: 131 (66.5%)  **FAIL**
    - FINAL_DATE: 165 (83.8%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 197 (100.0%)  *OK*
  - In Review: 99 (5.0%)
    - FILE_DATE: 99 (100.0%)  *OK*
    - PERMIT_DATE: 43 (43.4%)  **FAIL**
    - FINAL_DATE: 35 (35.4%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 99 (100.0%)  *OK*



## Atlanta GA

- Total records: 1,999
- Schemas: 
  - accela: 1,954 (97.7%)
  - custom: 45 (2.3%)
- STATUS_NORMALIZED not missing: 1,918 (95.9%)  *OK*
  - Active: 743 (38.7%)
    - FILE_DATE: 743 (100.0%)  *OK*
    - PERMIT_DATE: 705 (94.9%)  *OK*
    - FINAL_DATE: 116 (15.6%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 743 (100.0%)  *OK*
  - Final: 609 (31.8%)
    - FILE_DATE: 609 (100.0%)  *OK*
    - PERMIT_DATE: 128 (21.0%)  **FAIL**
    - FINAL_DATE: 21 (3.4%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 609 (100.0%)  *OK*
  - Inactive: 43 (2.2%)
    - FILE_DATE: 43 (100.0%)  *OK*
    - PERMIT_DATE: 5 (11.6%)  **FAIL**
    - FINAL_DATE: 1 (2.3%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 43 (100.0%)  *OK*
  - In Review: 523 (27.3%)
    - FILE_DATE: 523 (100.0%)  *OK*
    - PERMIT_DATE: 10 (1.9%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 523 (100.0%)  *OK*



## Omaha NE

- Total records: 1,999
- Schemas: 
  - accela: 1,982 (99.1%)
  - custom: 17 (0.9%)
- STATUS_NORMALIZED not missing: 1,955 (97.8%)  *OK*
  - Active: 1,445 (73.9%)
    - FILE_DATE: 1,445 (100.0%)  *OK*
    - PERMIT_DATE: 1,365 (94.5%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,445 (100.0%)  *OK*
  - Final: 375 (19.2%)
    - FILE_DATE: 375 (100.0%)  *OK*
    - PERMIT_DATE: 139 (37.1%)  **FAIL**
    - FINAL_DATE: 132 (35.2%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 375 (100.0%)  *OK*
  - Inactive: 48 (2.5%)
    - FILE_DATE: 48 (100.0%)  *OK*
    - PERMIT_DATE: 9 (18.7%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 48 (100.0%)  *OK*
  - In Review: 87 (4.5%)
    - FILE_DATE: 87 (100.0%)  *OK*
    - PERMIT_DATE: 1 (1.1%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 87 (100.0%)  *OK*



## El Paso County CO

- Total records: 2,001
- Schemas: 
  - custom: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 1,971 (98.5%)  *OK*
  - Active: 0 (0.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - Final: 1,834 (93.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 1,834 (100.0%)  *OK*
    - FINAL_DATE: 1,814 (98.9%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,834 (100.0%)  *OK*
  - Inactive: 122 (6.2%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 122 (100.0%)  *OK*
    - FINAL_DATE: 47 (38.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 122 (100.0%)  *OK*
  - In Review: 15 (0.8%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 15 (100.0%)  *OK*
    - FINAL_DATE: 6 (40.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 15 (100.0%)  *OK*



## Raleigh NC

- Total records: 2,002
- Schemas: 
  - energov: 2,002 (100.0%)
- STATUS_NORMALIZED not missing: 2,002 (100.0%)  *OK*
  - Active: 356 (17.8%)
    - FILE_DATE: 356 (100.0%)  *OK*
    - PERMIT_DATE: 356 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 356 (100.0%)  *OK*
  - Final: 1,365 (68.2%)
    - FILE_DATE: 1,365 (100.0%)  *OK*
    - PERMIT_DATE: 1,360 (99.6%)  *OK*
    - FINAL_DATE: 1,365 (100.0%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,365 (100.0%)  *OK*
  - Inactive: 175 (8.7%)
    - FILE_DATE: 175 (100.0%)  *OK*
    - PERMIT_DATE: 148 (84.6%)  **FAIL**
    - FINAL_DATE: 137 (78.3%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 175 (100.0%)  *OK*
  - In Review: 106 (5.3%)
    - FILE_DATE: 106 (100.0%)  *OK*
    - PERMIT_DATE: 2 (1.9%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 106 (100.0%)  *OK*



## Long Beach CA

- Total records: 2,000
- Schemas: 
  - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,100 (55.0%)  **FAIL**
  - Active: 129 (11.7%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 123 (95.3%)  *OK*
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - Final: 754 (68.5%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 750 (99.5%)  *OK*
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - Inactive: 143 (13.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 116 (81.1%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
  - In Review: 74 (6.7%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 0 (0.0%)  **FAIL**
    - FINAL_DATE: 68 (91.9%)  *OK*
    - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**



## Virginia Beach VA

- Total records: 2,002
- Schemas: 
  - accela: 2,002 (100.0%)
- STATUS_NORMALIZED not missing: 1,973 (98.6%)  *OK*
  - Active: 280 (14.2%)
    - FILE_DATE: 280 (100.0%)  *OK*
    - PERMIT_DATE: 219 (78.2%)  **FAIL**
    - FINAL_DATE: 2 (0.7%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 280 (100.0%)  *OK*
  - Final: 1,554 (78.8%)
    - FILE_DATE: 1,554 (100.0%)  *OK*
    - PERMIT_DATE: 1,285 (82.7%)  **FAIL**
    - FINAL_DATE: 1,098 (70.7%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1,554 (100.0%)  *OK*
  - Inactive: 65 (3.3%)
    - FILE_DATE: 65 (100.0%)  *OK*
    - PERMIT_DATE: 8 (12.3%)  **FAIL**
    - FINAL_DATE: 1 (1.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 65 (100.0%)  *OK*
  - In Review: 74 (3.8%)
    - FILE_DATE: 74 (100.0%)  *OK*
    - PERMIT_DATE: 3 (4.1%)  **FAIL**
    - FINAL_DATE: 1 (1.4%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 74 (100.0%)  *OK*



## Miami FL

- Total records: 1,999
- Schemas: 
  - custom: 1,999 (100.0%)
- STATUS_NORMALIZED not missing: 1,999 (100.0%)  *OK*
  - Active: 353 (17.7%)
    - FILE_DATE: 42 (11.9%)  **FAIL**
    - PERMIT_DATE: 353 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 353 (100.0%)  *OK*
  - Final: 1,529 (76.5%)
    - FILE_DATE: 370 (24.2%)  **FAIL**
    - PERMIT_DATE: 1,529 (100.0%)  *OK*
    - FINAL_DATE: 1,529 (100.0%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,529 (100.0%)  *OK*
  - Inactive: 115 (5.8%)
    - FILE_DATE: 44 (38.3%)  **FAIL**
    - PERMIT_DATE: 115 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 115 (100.0%)  *OK*
  - In Review: 2 (0.1%)
    - FILE_DATE: 1 (50.0%)  **FAIL**
    - PERMIT_DATE: 2 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 2 (100.0%)  *OK*



## Oakland CA

- Total records: 2,005
- Schemas: 
  - accela: 2,005 (100.0%)
- STATUS_NORMALIZED not missing: 1,922 (95.9%)  *OK*
  - Active: 329 (17.1%)
    - FILE_DATE: 329 (100.0%)  *OK*
    - PERMIT_DATE: 78 (23.7%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 329 (100.0%)  *OK*
  - Final: 917 (47.7%)
    - FILE_DATE: 917 (100.0%)  *OK*
    - PERMIT_DATE: 369 (40.2%)  **FAIL**
    - FINAL_DATE: 289 (31.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 917 (100.0%)  *OK*
  - Inactive: 543 (28.3%)
    - FILE_DATE: 543 (100.0%)  *OK*
    - PERMIT_DATE: 182 (33.5%)  **FAIL**
    - FINAL_DATE: 2 (0.4%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 543 (100.0%)  *OK*
  - In Review: 133 (6.9%)
    - FILE_DATE: 133 (100.0%)  *OK*
    - PERMIT_DATE: 5 (3.8%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 133 (100.0%)  *OK*



## Minneapolis MN

- Total records: 2,001
- Schemas: 
  - custom: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 2,001 (100.0%)  *OK*
  - Active: 317 (15.8%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 317 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 317 (100.0%)  *OK*
  - Final: 1,505 (75.2%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 1,505 (100.0%)  *OK*
    - FINAL_DATE: 1,505 (100.0%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,505 (100.0%)  *OK*
  - Inactive: 40 (2.0%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 40 (100.0%)  *OK*
    - FINAL_DATE: 14 (35.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 40 (100.0%)  *OK*
  - In Review: 139 (6.9%)
    - FILE_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_DATE: 139 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 139 (100.0%)  *OK*



## Tulsa OK

- Total records: 2,001
- Schemas: 
  - energov: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 2,001 (100.0%)  *OK*
  - Active: 281 (14.0%)
    - FILE_DATE: 281 (100.0%)  *OK*
    - PERMIT_DATE: 281 (100.0%)  *OK*
    - FINAL_DATE: 38 (13.5%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 281 (100.0%)  *OK*
  - Final: 1,283 (64.1%)
    - FILE_DATE: 1,283 (100.0%)  *OK*
    - PERMIT_DATE: 1,253 (97.7%)  *OK*
    - FINAL_DATE: 1,282 (99.9%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,283 (100.0%)  *OK*
  - Inactive: 333 (16.6%)
    - FILE_DATE: 333 (100.0%)  *OK*
    - PERMIT_DATE: 254 (76.3%)  **FAIL**
    - FINAL_DATE: 111 (33.3%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 333 (100.0%)  *OK*
  - In Review: 104 (5.2%)
    - FILE_DATE: 104 (100.0%)  *OK*
    - PERMIT_DATE: 20 (19.2%)  **FAIL**
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 104 (100.0%)  *OK*



## Bakersfield CA

- Total records: 2,000
- Schemas: 
  - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,981 (99.0%)  *OK*
  - Active: 427 (21.6%)
    - FILE_DATE: 427 (100.0%)  *OK*
    - PERMIT_DATE: 427 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 427 (100.0%)  *OK*
  - Final: 1,424 (71.9%)
    - FILE_DATE: 1,424 (100.0%)  *OK*
    - PERMIT_DATE: 1,424 (100.0%)  *OK*
    - FINAL_DATE: 1,390 (97.6%)  *OK*
    - PERMIT_OR_FILE_DATE: 1,424 (100.0%)  *OK*
  - Inactive: 37 (1.9%)
    - FILE_DATE: 37 (100.0%)  *OK*
    - PERMIT_DATE: 37 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 37 (100.0%)  *OK*
  - In Review: 93 (4.7%)
    - FILE_DATE: 93 (100.0%)  *OK*
    - PERMIT_DATE: 93 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 93 (100.0%)  *OK*



## Arlington TX

- Total records: 2,001
- Schemas: 
  - custom: 1,688 (84.4%)
  - nan: 0 (0.0%)
- STATUS_NORMALIZED not missing: 2,001 (100.0%)  *OK*
  - Active: 998 (49.9%)
    - FILE_DATE: 906 (90.8%)  *OK*
    - PERMIT_DATE: 998 (100.0%)  *OK*
    - FINAL_DATE: 255 (25.6%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 998 (100.0%)  *OK*
  - Final: 904 (45.2%)
    - FILE_DATE: 760 (84.1%)  **FAIL**
    - PERMIT_DATE: 904 (100.0%)  *OK*
    - FINAL_DATE: 144 (15.9%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 904 (100.0%)  *OK*
  - Inactive: 98 (4.9%)
    - FILE_DATE: 21 (21.4%)  **FAIL**
    - PERMIT_DATE: 98 (100.0%)  *OK*
    - FINAL_DATE: 16 (16.3%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 98 (100.0%)  *OK*
  - In Review: 1 (0.0%)
    - FILE_DATE: 1 (100.0%)  *OK*
    - PERMIT_DATE: 1 (100.0%)  *OK*
    - FINAL_DATE: 0 (0.0%)  **FAIL**
    - PERMIT_OR_FILE_DATE: 1 (100.0%)  *OK*



## By data requirements

- Require FILE_DATE for all permits, PERMIT_DATE for Active and Final, FINAL_DATE for Final: 8 / 49 meet criteria
- Require PERMIT_OR_FILE_DATE for all permits, FINAL_DATE for Final: 15 / 49 meet criteria
- Require PERMIT_OR_FILE_DATE for all permits: 40 / 49 meet criteria



## Conclusion

- PERMIT_OR_FILE_DATE appears mostly usable. 
- FINAL_DATE appears usable only for some jurisdictions. 
- Need to investigate:
  - If and when PERMIT_DATE and FILE_DATE are interchangeable
  - If and when FINAL_DATE is available
  - Why certain dates are not available for certain jurisdictions

