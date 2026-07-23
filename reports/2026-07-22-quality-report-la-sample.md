
# Building Permits Data Usability Report

For the jurisdictions in LA County, random sample of 2000 permits per city.  The jurisdctions are:

['Alhambra', 'Arcadia', 'Azusa', 'Beverly Hills', 'Burbank', 'Calabasas', 'Carson', 'Claremont', 'Compton', 'Culver City', 'Downey', 'El Segundo', 'Gardena', 'Glendale', 'Glendora', 'Hawthorne', 'Hermosa Beach', 'Inglewood', 'La Cañada Flintridge', 'La Habra', 'Lancaster', 'Lomita', 'Long Beach', 'Los Angeles', 'Los Angeles County', 'Manhattan Beach', 'Monterey Park', 'Palmdale', 'Palos Verdes Estates', 'Pasadena', 'Santa Clarita', 'Santa Monica', 'South El Monte', 'Torrance', 'Whittier']

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


## Alhambra CA 

- Total records: 2,000
- Schemas: 
    - energov: 1,906 (95.3%)
    - custom: 94 (4.7%)
- STATUS_NORMALIZED not missing: 1,913 (95.6%)  *OK*
    - Active: 483 (25.2%)
        - FILE_DATE: 483 (100.0%)  *OK*
        - PERMIT_DATE: 478 (99.0%)  *OK*
        - FINAL_DATE: 6 (1.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 483 (100.0%)  *OK*
    - Final: 464 (24.3%)
        - FILE_DATE: 464 (100.0%)  *OK*
        - PERMIT_DATE: 452 (97.4%)  *OK*
        - FINAL_DATE: 464 (100.0%)  *OK*
        - PERMIT_OR_FILE_DATE: 464 (100.0%)  *OK*
    - Inactive: 495 (25.9%)
        - FILE_DATE: 495 (100.0%)  *OK*
        - PERMIT_DATE: 392 (79.2%)  **FAIL**
        - FINAL_DATE: 80 (16.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 495 (100.0%)  *OK*
    - In Review: 471 (24.6%)
        - FILE_DATE: 471 (100.0%)  *OK*
        - PERMIT_DATE: 26 (5.5%)  **FAIL**
        - FINAL_DATE: 1 (0.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 471 (100.0%)  *OK*

## Arcadia CA 

- Total records: 2,000
- Schemas: 
    - energov: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 2,000 (100.0%)  *OK*
    - Active: 137 (6.8%)
        - FILE_DATE: 137 (100.0%)  *OK*
        - PERMIT_DATE: 124 (90.5%)  *OK*
        - FINAL_DATE: 49 (35.8%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 137 (100.0%)  *OK*
    - Final: 1,673 (83.6%)
        - FILE_DATE: 1,673 (100.0%)  *OK*
        - PERMIT_DATE: 1,640 (98.0%)  *OK*
        - FINAL_DATE: 1,645 (98.3%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,673 (100.0%)  *OK*
    - Inactive: 190 (9.5%)
        - FILE_DATE: 190 (100.0%)  *OK*
        - PERMIT_DATE: 170 (89.5%)  *OK*
        - FINAL_DATE: 20 (10.5%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 190 (100.0%)  *OK*
    - In Review: 0 (0.0%)
        - FILE_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**

## Azusa CA 

- Total records: 2,000
- Schemas: 
    - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,999 (99.9%)  *OK*
    - Active: 337 (16.9%)
        - FILE_DATE: 337 (100.0%)  *OK*
        - PERMIT_DATE: 337 (100.0%)  *OK*
        - FINAL_DATE: 266 (78.9%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 337 (100.0%)  *OK*
    - Final: 1,320 (66.0%)
        - FILE_DATE: 1,320 (100.0%)  *OK*
        - PERMIT_DATE: 1,307 (99.0%)  *OK*
        - FINAL_DATE: 1,192 (90.3%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,320 (100.0%)  *OK*
    - Inactive: 247 (12.4%)
        - FILE_DATE: 247 (100.0%)  *OK*
        - PERMIT_DATE: 210 (85.0%)  *OK*
        - FINAL_DATE: 227 (91.9%)  *OK*
        - PERMIT_OR_FILE_DATE: 247 (100.0%)  *OK*
    - In Review: 95 (4.8%)
        - FILE_DATE: 95 (100.0%)  *OK*
        - PERMIT_DATE: 27 (28.4%)  **FAIL**
        - FINAL_DATE: 61 (64.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 95 (100.0%)  *OK*

## Beverly Hills CA 

- Total records: 1,999
- Schemas: 
    - custom: 1,999 (100.0%)
- STATUS_NORMALIZED not missing: 1,974 (98.7%)  *OK*
    - Active: 815 (41.3%)
        - FILE_DATE: 808 (99.1%)  *OK*
        - PERMIT_DATE: 737 (90.4%)  *OK*
        - FINAL_DATE: 644 (79.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 814 (99.9%)  *OK*
    - Final: 1,140 (57.8%)
        - FILE_DATE: 1,135 (99.6%)  *OK*
        - PERMIT_DATE: 1,106 (97.0%)  *OK*
        - FINAL_DATE: 1,106 (97.0%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,138 (99.8%)  *OK*
    - Inactive: 19 (1.0%)
        - FILE_DATE: 19 (100.0%)  *OK*
        - PERMIT_DATE: 7 (36.8%)  **FAIL**
        - FINAL_DATE: 15 (78.9%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 19 (100.0%)  *OK*
    - In Review: 0 (0.0%)
        - FILE_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**

## Burbank CA 

- Total records: 2,001
- Schemas: 
    - custom: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 1,999 (99.9%)  *OK*
    - Active: 230 (11.5%)
        - FILE_DATE: 229 (99.6%)  *OK*
        - PERMIT_DATE: 171 (74.3%)  **FAIL**
        - FINAL_DATE: 25 (10.9%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 229 (99.6%)  *OK*
    - Final: 336 (16.8%)
        - FILE_DATE: 336 (100.0%)  *OK*
        - PERMIT_DATE: 335 (99.7%)  *OK*
        - FINAL_DATE: 335 (99.7%)  *OK*
        - PERMIT_OR_FILE_DATE: 336 (100.0%)  *OK*
    - Inactive: 1,148 (57.4%)
        - FILE_DATE: 1,140 (99.3%)  *OK*
        - PERMIT_DATE: 548 (47.7%)  **FAIL**
        - FINAL_DATE: 36 (3.1%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 1,144 (99.7%)  *OK*
    - In Review: 285 (14.3%)
        - FILE_DATE: 284 (99.6%)  *OK*
        - PERMIT_DATE: 59 (20.7%)  **FAIL**
        - FINAL_DATE: 126 (44.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 284 (99.6%)  *OK*

## Calabasas CA 

- Total records: 2,000
- Schemas: 
    - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,604 (80.2%)  **FAIL**
    - Active: 53 (3.3%)
        - FILE_DATE: 53 (100.0%)  *OK*
        - PERMIT_DATE: 53 (100.0%)  *OK*
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 53 (100.0%)  *OK*
    - Final: 1,369 (85.3%)
        - FILE_DATE: 1,369 (100.0%)  *OK*
        - PERMIT_DATE: 1,288 (94.1%)  *OK*
        - FINAL_DATE: 1,214 (88.7%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,369 (100.0%)  *OK*
    - Inactive: 134 (8.4%)
        - FILE_DATE: 134 (100.0%)  *OK*
        - PERMIT_DATE: 101 (75.4%)  **FAIL**
        - FINAL_DATE: 6 (4.5%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 134 (100.0%)  *OK*
    - In Review: 48 (3.0%)
        - FILE_DATE: 48 (100.0%)  *OK*
        - PERMIT_DATE: 42 (87.5%)  *OK*
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 48 (100.0%)  *OK*

## Carson CA 

- Total records: 2,000
- Schemas: 
    - energov: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,707 (85.3%)  *OK*
    - Active: 806 (47.2%)
        - FILE_DATE: 806 (100.0%)  *OK*
        - PERMIT_DATE: 806 (100.0%)  *OK*
        - FINAL_DATE: 2 (0.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 806 (100.0%)  *OK*
    - Final: 241 (14.1%)
        - FILE_DATE: 241 (100.0%)  *OK*
        - PERMIT_DATE: 195 (80.9%)  **FAIL**
        - FINAL_DATE: 241 (100.0%)  *OK*
        - PERMIT_OR_FILE_DATE: 241 (100.0%)  *OK*
    - Inactive: 124 (7.3%)
        - FILE_DATE: 124 (100.0%)  *OK*
        - PERMIT_DATE: 9 (7.3%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 124 (100.0%)  *OK*
    - In Review: 536 (31.4%)
        - FILE_DATE: 536 (100.0%)  *OK*
        - PERMIT_DATE: 5 (0.9%)  **FAIL**
        - FINAL_DATE: 1 (0.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 536 (100.0%)  *OK*

## Claremont CA 

- Total records: 2,000
- Schemas: 
    - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 2,000 (100.0%)  *OK*
    - Active: 252 (12.6%)
        - FILE_DATE: 252 (100.0%)  *OK*
        - PERMIT_DATE: 229 (90.9%)  *OK*
        - FINAL_DATE: 206 (81.7%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 252 (100.0%)  *OK*
    - Final: 1,045 (52.2%)
        - FILE_DATE: 1,045 (100.0%)  *OK*
        - PERMIT_DATE: 1,009 (96.6%)  *OK*
        - FINAL_DATE: 1,013 (96.9%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,045 (100.0%)  *OK*
    - Inactive: 322 (16.1%)
        - FILE_DATE: 322 (100.0%)  *OK*
        - PERMIT_DATE: 305 (94.7%)  *OK*
        - FINAL_DATE: 318 (98.8%)  *OK*
        - PERMIT_OR_FILE_DATE: 322 (100.0%)  *OK*
    - In Review: 381 (19.0%)
        - FILE_DATE: 381 (100.0%)  *OK*
        - PERMIT_DATE: 170 (44.6%)  **FAIL**
        - FINAL_DATE: 344 (90.3%)  *OK*
        - PERMIT_OR_FILE_DATE: 381 (100.0%)  *OK*

## Compton CA 

- Total records: 2,000
- Schemas: 
    - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,886 (94.3%)  *OK*
    - Active: 1,133 (60.1%)
        - FILE_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_DATE: 1,058 (93.4%)  *OK*
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 1,058 (93.4%)  *OK*
    - Final: 384 (20.4%)
        - FILE_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_DATE: 374 (97.4%)  *OK*
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 374 (97.4%)  *OK*
    - Inactive: 78 (4.1%)
        - FILE_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_DATE: 47 (60.3%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 47 (60.3%)  **FAIL**
    - In Review: 291 (15.4%)
        - FILE_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_DATE: 40 (13.7%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 40 (13.7%)  **FAIL**

## Culver City CA 

- Total records: 2,000
- Schemas: 
    - accela: 874 (43.7%)
    - custom: 1,126 (56.3%)
- STATUS_NORMALIZED not missing: 1,992 (99.6%)  *OK*
    - Active: 249 (12.5%)
        - FILE_DATE: 249 (100.0%)  *OK*
        - PERMIT_DATE: 101 (40.6%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 249 (100.0%)  *OK*
    - Final: 1,626 (81.6%)
        - FILE_DATE: 1,626 (100.0%)  *OK*
        - PERMIT_DATE: 504 (31.0%)  **FAIL**
        - FINAL_DATE: 773 (47.5%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 1,626 (100.0%)  *OK*
    - Inactive: 65 (3.3%)
        - FILE_DATE: 65 (100.0%)  *OK*
        - PERMIT_DATE: 10 (15.4%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 65 (100.0%)  *OK*
    - In Review: 52 (2.6%)
        - FILE_DATE: 52 (100.0%)  *OK*
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 52 (100.0%)  *OK*

## Downey CA 

- Total records: 2,001
- Schemas: 
    - accela: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 1,996 (99.8%)  *OK*
    - Active: 377 (18.9%)
        - FILE_DATE: 377 (100.0%)  *OK*
        - PERMIT_DATE: 147 (39.0%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 377 (100.0%)  *OK*
    - Final: 1,298 (65.0%)
        - FILE_DATE: 1,298 (100.0%)  *OK*
        - PERMIT_DATE: 1,250 (96.3%)  *OK*
        - FINAL_DATE: 1,147 (88.4%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,298 (100.0%)  *OK*
    - Inactive: 213 (10.7%)
        - FILE_DATE: 213 (100.0%)  *OK*
        - PERMIT_DATE: 142 (66.7%)  **FAIL**
        - FINAL_DATE: 16 (7.5%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 213 (100.0%)  *OK*
    - In Review: 108 (5.4%)
        - FILE_DATE: 108 (100.0%)  *OK*
        - PERMIT_DATE: 4 (3.7%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 108 (100.0%)  *OK*

## El Segundo CA 

- Total records: 2,000
- Schemas: 
    - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,996 (99.8%)  *OK*
    - Active: 338 (16.9%)
        - FILE_DATE: 338 (100.0%)  *OK*
        - PERMIT_DATE: 319 (94.4%)  *OK*
        - FINAL_DATE: 5 (1.5%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 338 (100.0%)  *OK*
    - Final: 1,137 (57.0%)
        - FILE_DATE: 1,137 (100.0%)  *OK*
        - PERMIT_DATE: 1,116 (98.2%)  *OK*
        - FINAL_DATE: 1,112 (97.8%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,137 (100.0%)  *OK*
    - Inactive: 451 (22.6%)
        - FILE_DATE: 447 (99.1%)  *OK*
        - PERMIT_DATE: 308 (68.3%)  **FAIL**
        - FINAL_DATE: 10 (2.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 447 (99.1%)  *OK*
    - In Review: 70 (3.5%)
        - FILE_DATE: 64 (91.4%)  *OK*
        - PERMIT_DATE: 4 (5.7%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 64 (91.4%)  *OK*

## Gardena CA 

- Total records: 2,000
- Schemas: 
    - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,801 (90.0%)  *OK*
    - Active: 152 (8.4%)
        - FILE_DATE: 151 (99.3%)  *OK*
        - PERMIT_DATE: 138 (90.8%)  *OK*
        - FINAL_DATE: 7 (4.6%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 151 (99.3%)  *OK*
    - Final: 1,241 (68.9%)
        - FILE_DATE: 1,241 (100.0%)  *OK*
        - PERMIT_DATE: 1,105 (89.0%)  *OK*
        - FINAL_DATE: 1,209 (97.4%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,241 (100.0%)  *OK*
    - Inactive: 313 (17.4%)
        - FILE_DATE: 311 (99.4%)  *OK*
        - PERMIT_DATE: 252 (80.5%)  **FAIL**
        - FINAL_DATE: 2 (0.6%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 311 (99.4%)  *OK*
    - In Review: 95 (5.3%)
        - FILE_DATE: 94 (98.9%)  *OK*
        - PERMIT_DATE: 5 (5.3%)  **FAIL**
        - FINAL_DATE: 23 (24.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 94 (98.9%)  *OK*

## Glendale CA 

- Total records: 2,001
- Schemas: 
    - energov: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 2,001 (100.0%)  *OK*
    - Active: 323 (16.1%)
        - FILE_DATE: 323 (100.0%)  *OK*
        - PERMIT_DATE: 321 (99.4%)  *OK*
        - FINAL_DATE: 174 (53.9%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 323 (100.0%)  *OK*
    - Final: 1,144 (57.2%)
        - FILE_DATE: 1,144 (100.0%)  *OK*
        - PERMIT_DATE: 1,112 (97.2%)  *OK*
        - FINAL_DATE: 1,144 (100.0%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,144 (100.0%)  *OK*
    - Inactive: 381 (19.0%)
        - FILE_DATE: 381 (100.0%)  *OK*
        - PERMIT_DATE: 275 (72.2%)  **FAIL**
        - FINAL_DATE: 101 (26.5%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 381 (100.0%)  *OK*
    - In Review: 153 (7.6%)
        - FILE_DATE: 153 (100.0%)  *OK*
        - PERMIT_DATE: 39 (25.5%)  **FAIL**
        - FINAL_DATE: 12 (7.8%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 153 (100.0%)  *OK*

## Glendora CA 

- Total records: 2,000
- Schemas: 
    - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,999 (99.9%)  *OK*
    - Active: 758 (37.9%)
        - FILE_DATE: 758 (100.0%)  *OK*
        - PERMIT_DATE: 654 (86.3%)  *OK*
        - FINAL_DATE: 3 (0.4%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 758 (100.0%)  *OK*
    - Final: 946 (47.3%)
        - FILE_DATE: 946 (100.0%)  *OK*
        - PERMIT_DATE: 933 (98.6%)  *OK*
        - FINAL_DATE: 935 (98.8%)  *OK*
        - PERMIT_OR_FILE_DATE: 946 (100.0%)  *OK*
    - Inactive: 129 (6.5%)
        - FILE_DATE: 129 (100.0%)  *OK*
        - PERMIT_DATE: 105 (81.4%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 129 (100.0%)  *OK*
    - In Review: 166 (8.3%)
        - FILE_DATE: 166 (100.0%)  *OK*
        - PERMIT_DATE: 3 (1.8%)  **FAIL**
        - FINAL_DATE: 1 (0.6%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 166 (100.0%)  *OK*

## Hawthorne CA 

- Total records: 1,899
- Schemas: 
    - energov: 1,899 (100.0%)
- STATUS_NORMALIZED not missing: 1,899 (100.0%)  *OK*
    - Active: 305 (16.1%)
        - FILE_DATE: 305 (100.0%)  *OK*
        - PERMIT_DATE: 305 (100.0%)  *OK*
        - FINAL_DATE: 2 (0.7%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 305 (100.0%)  *OK*
    - Final: 366 (19.3%)
        - FILE_DATE: 366 (100.0%)  *OK*
        - PERMIT_DATE: 366 (100.0%)  *OK*
        - FINAL_DATE: 366 (100.0%)  *OK*
        - PERMIT_OR_FILE_DATE: 366 (100.0%)  *OK*
    - Inactive: 379 (20.0%)
        - FILE_DATE: 379 (100.0%)  *OK*
        - PERMIT_DATE: 267 (70.4%)  **FAIL**
        - FINAL_DATE: 14 (3.7%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 379 (100.0%)  *OK*
    - In Review: 849 (44.7%)
        - FILE_DATE: 849 (100.0%)  *OK*
        - PERMIT_DATE: 100 (11.8%)  **FAIL**
        - FINAL_DATE: 3 (0.4%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 849 (100.0%)  *OK*

## Hermosa Beach CA 

- Total records: 2,000
- Schemas: 
    - accela: 1,999 (99.9%)
    - custom: 1 (0.0%)
- STATUS_NORMALIZED not missing: 1,981 (99.0%)  *OK*
    - Active: 193 (9.7%)
        - FILE_DATE: 193 (100.0%)  *OK*
        - PERMIT_DATE: 169 (87.6%)  *OK*
        - FINAL_DATE: 4 (2.1%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 193 (100.0%)  *OK*
    - Final: 1,520 (76.7%)
        - FILE_DATE: 1,520 (100.0%)  *OK*
        - PERMIT_DATE: 1,280 (84.2%)  **FAIL**
        - FINAL_DATE: 1,303 (85.7%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,520 (100.0%)  *OK*
    - Inactive: 162 (8.2%)
        - FILE_DATE: 162 (100.0%)  *OK*
        - PERMIT_DATE: 120 (74.1%)  **FAIL**
        - FINAL_DATE: 3 (1.9%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 162 (100.0%)  *OK*
    - In Review: 106 (5.4%)
        - FILE_DATE: 106 (100.0%)  *OK*
        - PERMIT_DATE: 1 (0.9%)  **FAIL**
        - FINAL_DATE: 1 (0.9%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 106 (100.0%)  *OK*

## Inglewood CA 

- Total records: 2,000
- Schemas: 
    - custom: 1,442 (72.1%)
    - accela: 558 (27.9%)
- STATUS_NORMALIZED not missing: 484 (24.2%)  **FAIL**
    - Active: 86 (17.8%)
        - FILE_DATE: 86 (100.0%)  *OK*
        - PERMIT_DATE: 33 (38.4%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 86 (100.0%)  *OK*
    - Final: 76 (15.7%)
        - FILE_DATE: 76 (100.0%)  *OK*
        - PERMIT_DATE: 73 (96.1%)  *OK*
        - FINAL_DATE: 75 (98.7%)  *OK*
        - PERMIT_OR_FILE_DATE: 76 (100.0%)  *OK*
    - Inactive: 5 (1.0%)
        - FILE_DATE: 5 (100.0%)  *OK*
        - PERMIT_DATE: 4 (80.0%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 5 (100.0%)  *OK*
    - In Review: 317 (65.5%)
        - FILE_DATE: 317 (100.0%)  *OK*
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 2 (0.6%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 317 (100.0%)  *OK*

## La Cañada Flintridge CA 

- Total records: 2,000
- Schemas: 
    - energov: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,836 (91.8%)  *OK*
    - Active: 231 (12.6%)
        - FILE_DATE: 231 (100.0%)  *OK*
        - PERMIT_DATE: 231 (100.0%)  *OK*
        - FINAL_DATE: 8 (3.5%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 231 (100.0%)  *OK*
    - Final: 873 (47.5%)
        - FILE_DATE: 873 (100.0%)  *OK*
        - PERMIT_DATE: 871 (99.8%)  *OK*
        - FINAL_DATE: 873 (100.0%)  *OK*
        - PERMIT_OR_FILE_DATE: 873 (100.0%)  *OK*
    - Inactive: 553 (30.1%)
        - FILE_DATE: 553 (100.0%)  *OK*
        - PERMIT_DATE: 270 (48.8%)  **FAIL**
        - FINAL_DATE: 221 (40.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 553 (100.0%)  *OK*
    - In Review: 179 (9.7%)
        - FILE_DATE: 179 (100.0%)  *OK*
        - PERMIT_DATE: 1 (0.6%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 179 (100.0%)  *OK*

## La Habra CA 

- Total records: 2,000
- Schemas: 
    - energov: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 2,000 (100.0%)  *OK*
    - Active: 181 (9.0%)
        - FILE_DATE: 181 (100.0%)  *OK*
        - PERMIT_DATE: 181 (100.0%)  *OK*
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 181 (100.0%)  *OK*
    - Final: 1,481 (74.0%)
        - FILE_DATE: 1,481 (100.0%)  *OK*
        - PERMIT_DATE: 1,396 (94.3%)  *OK*
        - FINAL_DATE: 1,397 (94.3%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,481 (100.0%)  *OK*
    - Inactive: 186 (9.3%)
        - FILE_DATE: 186 (100.0%)  *OK*
        - PERMIT_DATE: 180 (96.8%)  *OK*
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 186 (100.0%)  *OK*
    - In Review: 152 (7.6%)
        - FILE_DATE: 152 (100.0%)  *OK*
        - PERMIT_DATE: 20 (13.2%)  **FAIL**
        - FINAL_DATE: 12 (7.9%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 152 (100.0%)  *OK*

## Lancaster CA 

- Total records: 2,000
- Schemas: 
    - accela: 1,997 (99.8%)
    - custom: 3 (0.1%)
- STATUS_NORMALIZED not missing: 1,953 (97.6%)  *OK*
    - Active: 339 (17.4%)
        - FILE_DATE: 339 (100.0%)  *OK*
        - PERMIT_DATE: 334 (98.5%)  *OK*
        - FINAL_DATE: 29 (8.6%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 339 (100.0%)  *OK*
    - Final: 1,214 (62.2%)
        - FILE_DATE: 1,214 (100.0%)  *OK*
        - PERMIT_DATE: 497 (40.9%)  **FAIL**
        - FINAL_DATE: 501 (41.3%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 1,214 (100.0%)  *OK*
    - Inactive: 178 (9.1%)
        - FILE_DATE: 178 (100.0%)  *OK*
        - PERMIT_DATE: 49 (27.5%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 178 (100.0%)  *OK*
    - In Review: 222 (11.4%)
        - FILE_DATE: 222 (100.0%)  *OK*
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 1 (0.5%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 222 (100.0%)  *OK*

## Lomita CA 

- Total records: 2,000
- Schemas: 
    - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 2,000 (100.0%)  *OK*
    - Active: 254 (12.7%)
        - FILE_DATE: 254 (100.0%)  *OK*
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 254 (100.0%)  *OK*
    - Final: 1,528 (76.4%)
        - FILE_DATE: 1,527 (99.9%)  *OK*
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 1,527 (99.9%)  *OK*
    - Inactive: 128 (6.4%)
        - FILE_DATE: 128 (100.0%)  *OK*
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 128 (100.0%)  *OK*
    - In Review: 90 (4.5%)
        - FILE_DATE: 90 (100.0%)  *OK*
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 90 (100.0%)  *OK*

## Long Beach CA 

- Total records: 2,000
- Schemas: 
    - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,103 (55.1%)  **FAIL**
    - Active: 110 (10.0%)
        - FILE_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 109 (99.1%)  *OK*
        - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
    - Final: 775 (70.3%)
        - FILE_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 767 (99.0%)  *OK*
        - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
    - Inactive: 149 (13.5%)
        - FILE_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 124 (83.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**
    - In Review: 69 (6.3%)
        - FILE_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 62 (89.9%)  *OK*
        - PERMIT_OR_FILE_DATE: 0 (0.0%)  **FAIL**

## Los Angeles CA 

- Total records: 2,002
- Schemas: 
    - custom: 2,002 (100.0%)
- STATUS_NORMALIZED not missing: 1,879 (93.9%)  *OK*
    - Active: 257 (13.7%)
        - FILE_DATE: 68 (26.5%)  **FAIL**
        - PERMIT_DATE: 257 (100.0%)  *OK*
        - FINAL_DATE: 2 (0.8%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 257 (100.0%)  *OK*
    - Final: 1,323 (70.4%)
        - FILE_DATE: 351 (26.5%)  **FAIL**
        - PERMIT_DATE: 1,322 (99.9%)  *OK*
        - FINAL_DATE: 1,295 (97.9%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,323 (100.0%)  *OK*
    - Inactive: 128 (6.8%)
        - FILE_DATE: 26 (20.3%)  **FAIL**
        - PERMIT_DATE: 113 (88.3%)  *OK*
        - FINAL_DATE: 2 (1.6%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 122 (95.3%)  *OK*
    - In Review: 171 (9.1%)
        - FILE_DATE: 156 (91.2%)  *OK*
        - PERMIT_DATE: 6 (3.5%)  **FAIL**
        - FINAL_DATE: 2 (1.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 158 (92.4%)  *OK*

## Los Angeles County CA 

- Total records: 1,999
- Schemas: 
    - energov: 1,998 (99.9%)
    - custom: 1 (0.1%)
- STATUS_NORMALIZED not missing: 1,999 (100.0%)  *OK*
    - Active: 519 (26.0%)
        - FILE_DATE: 519 (100.0%)  *OK*
        - PERMIT_DATE: 519 (100.0%)  *OK*
        - FINAL_DATE: 20 (3.9%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 519 (100.0%)  *OK*
    - Final: 972 (48.6%)
        - FILE_DATE: 972 (100.0%)  *OK*
        - PERMIT_DATE: 950 (97.7%)  *OK*
        - FINAL_DATE: 972 (100.0%)  *OK*
        - PERMIT_OR_FILE_DATE: 972 (100.0%)  *OK*
    - Inactive: 225 (11.3%)
        - FILE_DATE: 225 (100.0%)  *OK*
        - PERMIT_DATE: 36 (16.0%)  **FAIL**
        - FINAL_DATE: 4 (1.8%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 225 (100.0%)  *OK*
    - In Review: 283 (14.2%)
        - FILE_DATE: 283 (100.0%)  *OK*
        - PERMIT_DATE: 18 (6.4%)  **FAIL**
        - FINAL_DATE: 4 (1.4%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 283 (100.0%)  *OK*

## Manhattan Beach CA 

- Total records: 2,000
- Schemas: 
    - energov: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 2,000 (100.0%)  *OK*
    - Active: 423 (21.1%)
        - FILE_DATE: 423 (100.0%)  *OK*
        - PERMIT_DATE: 420 (99.3%)  *OK*
        - FINAL_DATE: 3 (0.7%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 423 (100.0%)  *OK*
    - Final: 1,028 (51.4%)
        - FILE_DATE: 1,028 (100.0%)  *OK*
        - PERMIT_DATE: 1,025 (99.7%)  *OK*
        - FINAL_DATE: 1,026 (99.8%)  *OK*
        - PERMIT_OR_FILE_DATE: 1,028 (100.0%)  *OK*
    - Inactive: 427 (21.3%)
        - FILE_DATE: 427 (100.0%)  *OK*
        - PERMIT_DATE: 301 (70.5%)  **FAIL**
        - FINAL_DATE: 131 (30.7%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 427 (100.0%)  *OK*
    - In Review: 122 (6.1%)
        - FILE_DATE: 122 (100.0%)  *OK*
        - PERMIT_DATE: 13 (10.7%)  **FAIL**
        - FINAL_DATE: 11 (9.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 122 (100.0%)  *OK*

## Monterey Park CA 

- Total records: 2,000
- Schemas: 
    - accela: 1,985 (99.2%)
    - custom: 15 (0.7%)
- STATUS_NORMALIZED not missing: 1,997 (99.8%)  *OK*
    - Active: 534 (26.7%)
        - FILE_DATE: 534 (100.0%)  *OK*
        - PERMIT_DATE: 314 (58.8%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 534 (100.0%)  *OK*
    - Final: 988 (49.5%)
        - FILE_DATE: 988 (100.0%)  *OK*
        - PERMIT_DATE: 930 (94.1%)  *OK*
        - FINAL_DATE: 919 (93.0%)  *OK*
        - PERMIT_OR_FILE_DATE: 988 (100.0%)  *OK*
    - Inactive: 252 (12.6%)
        - FILE_DATE: 252 (100.0%)  *OK*
        - PERMIT_DATE: 177 (70.2%)  **FAIL**
        - FINAL_DATE: 1 (0.4%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 252 (100.0%)  *OK*
    - In Review: 223 (11.2%)
        - FILE_DATE: 223 (100.0%)  *OK*
        - PERMIT_DATE: 3 (1.3%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 223 (100.0%)  *OK*

## Palmdale CA 

- Total records: 2,000
- Schemas: 
    - accela: 1,983 (99.1%)
    - custom: 17 (0.8%)
- STATUS_NORMALIZED not missing: 1,795 (89.7%)  *OK*
    - Active: 209 (11.6%)
        - FILE_DATE: 209 (100.0%)  *OK*
        - PERMIT_DATE: 31 (14.8%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 209 (100.0%)  *OK*
    - Final: 1,151 (64.1%)
        - FILE_DATE: 1,151 (100.0%)  *OK*
        - PERMIT_DATE: 58 (5.0%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 1,151 (100.0%)  *OK*
    - Inactive: 314 (17.5%)
        - FILE_DATE: 314 (100.0%)  *OK*
        - PERMIT_DATE: 17 (5.4%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 314 (100.0%)  *OK*
    - In Review: 121 (6.7%)
        - FILE_DATE: 121 (100.0%)  *OK*
        - PERMIT_DATE: 3 (2.5%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 121 (100.0%)  *OK*

## Palos Verdes Estates CA 

- Total records: 2,000
- Schemas: 
    - custom: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,527 (76.3%)  **FAIL**
    - Active: 145 (9.5%)
        - FILE_DATE: 145 (100.0%)  *OK*
        - PERMIT_DATE: 143 (98.6%)  *OK*
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 145 (100.0%)  *OK*
    - Final: 894 (58.5%)
        - FILE_DATE: 894 (100.0%)  *OK*
        - PERMIT_DATE: 894 (100.0%)  *OK*
        - FINAL_DATE: 893 (99.9%)  *OK*
        - PERMIT_OR_FILE_DATE: 894 (100.0%)  *OK*
    - Inactive: 373 (24.4%)
        - FILE_DATE: 373 (100.0%)  *OK*
        - PERMIT_DATE: 347 (93.0%)  *OK*
        - FINAL_DATE: 5 (1.3%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 373 (100.0%)  *OK*
    - In Review: 115 (7.5%)
        - FILE_DATE: 115 (100.0%)  *OK*
        - PERMIT_DATE: 7 (6.1%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 115 (100.0%)  *OK*

## Pasadena CA 

- Total records: 1,998
- Schemas: 
    - energov: 1,960 (98.1%)
    - custom: 38 (1.9%)
- STATUS_NORMALIZED not missing: 1,998 (100.0%)  *OK*
    - Active: 553 (27.7%)
        - FILE_DATE: 553 (100.0%)  *OK*
        - PERMIT_DATE: 536 (96.9%)  *OK*
        - FINAL_DATE: 371 (67.1%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 553 (100.0%)  *OK*
    - Final: 908 (45.4%)
        - FILE_DATE: 908 (100.0%)  *OK*
        - PERMIT_DATE: 865 (95.3%)  *OK*
        - FINAL_DATE: 877 (96.6%)  *OK*
        - PERMIT_OR_FILE_DATE: 908 (100.0%)  *OK*
    - Inactive: 467 (23.4%)
        - FILE_DATE: 467 (100.0%)  *OK*
        - PERMIT_DATE: 336 (71.9%)  **FAIL**
        - FINAL_DATE: 28 (6.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 467 (100.0%)  *OK*
    - In Review: 70 (3.5%)
        - FILE_DATE: 70 (100.0%)  *OK*
        - PERMIT_DATE: 2 (2.9%)  **FAIL**
        - FINAL_DATE: 2 (2.9%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 70 (100.0%)  *OK*

## Santa Clarita CA 

- Total records: 1,999
- Schemas: 
    - accela: 1,918 (95.9%)
    - custom: 81 (4.1%)
- STATUS_NORMALIZED not missing: 1,991 (99.6%)  *OK*
    - Active: 195 (9.8%)
        - FILE_DATE: 195 (100.0%)  *OK*
        - PERMIT_DATE: 146 (74.9%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 195 (100.0%)  *OK*
    - Final: 1,529 (76.8%)
        - FILE_DATE: 1,529 (100.0%)  *OK*
        - PERMIT_DATE: 355 (23.2%)  **FAIL**
        - FINAL_DATE: 367 (24.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 1,529 (100.0%)  *OK*
    - Inactive: 207 (10.4%)
        - FILE_DATE: 207 (100.0%)  *OK*
        - PERMIT_DATE: 7 (3.4%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 207 (100.0%)  *OK*
    - In Review: 60 (3.0%)
        - FILE_DATE: 60 (100.0%)  *OK*
        - PERMIT_DATE: 0 (0.0%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 60 (100.0%)  *OK*

## Santa Monica CA 

- Total records: 2,000
- Schemas: 
    - accela: 1,988 (99.4%)
    - custom: 12 (0.6%)
- STATUS_NORMALIZED not missing: 1,983 (99.1%)  *OK*
    - Active: 142 (7.2%)
        - FILE_DATE: 142 (100.0%)  *OK*
        - PERMIT_DATE: 89 (62.7%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 142 (100.0%)  *OK*
    - Final: 939 (47.4%)
        - FILE_DATE: 939 (100.0%)  *OK*
        - PERMIT_DATE: 490 (52.2%)  **FAIL**
        - FINAL_DATE: 505 (53.8%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 939 (100.0%)  *OK*
    - Inactive: 567 (28.6%)
        - FILE_DATE: 567 (100.0%)  *OK*
        - PERMIT_DATE: 74 (13.1%)  **FAIL**
        - FINAL_DATE: 2 (0.4%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 567 (100.0%)  *OK*
    - In Review: 335 (16.9%)
        - FILE_DATE: 335 (100.0%)  *OK*
        - PERMIT_DATE: 84 (25.1%)  **FAIL**
        - FINAL_DATE: 4 (1.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 335 (100.0%)  *OK*

## South El Monte CA 

- Total records: 2,000
- Schemas: 
    - accela: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,996 (99.8%)  *OK*
    - Active: 409 (20.5%)
        - FILE_DATE: 409 (100.0%)  *OK*
        - PERMIT_DATE: 372 (91.0%)  *OK*
        - FINAL_DATE: 3 (0.7%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 409 (100.0%)  *OK*
    - Final: 391 (19.6%)
        - FILE_DATE: 391 (100.0%)  *OK*
        - PERMIT_DATE: 305 (78.0%)  **FAIL**
        - FINAL_DATE: 318 (81.3%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 391 (100.0%)  *OK*
    - Inactive: 258 (12.9%)
        - FILE_DATE: 258 (100.0%)  *OK*
        - PERMIT_DATE: 4 (1.6%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 258 (100.0%)  *OK*
    - In Review: 938 (47.0%)
        - FILE_DATE: 938 (100.0%)  *OK*
        - PERMIT_DATE: 2 (0.2%)  **FAIL**
        - FINAL_DATE: 1 (0.1%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 938 (100.0%)  *OK*

## Torrance CA 

- Total records: 2,001
- Schemas: 
    - accela: 2,001 (100.0%)
- STATUS_NORMALIZED not missing: 1,997 (99.8%)  *OK*
    - Active: 469 (23.5%)
        - FILE_DATE: 469 (100.0%)  *OK*
        - PERMIT_DATE: 430 (91.7%)  *OK*
        - FINAL_DATE: 1 (0.2%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 469 (100.0%)  *OK*
    - Final: 593 (29.7%)
        - FILE_DATE: 593 (100.0%)  *OK*
        - PERMIT_DATE: 593 (100.0%)  *OK*
        - FINAL_DATE: 591 (99.7%)  *OK*
        - PERMIT_OR_FILE_DATE: 593 (100.0%)  *OK*
    - Inactive: 78 (3.9%)
        - FILE_DATE: 78 (100.0%)  *OK*
        - PERMIT_DATE: 45 (57.7%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 78 (100.0%)  *OK*
    - In Review: 857 (42.9%)
        - FILE_DATE: 857 (100.0%)  *OK*
        - PERMIT_DATE: 766 (89.4%)  *OK*
        - FINAL_DATE: 729 (85.1%)  *OK*
        - PERMIT_OR_FILE_DATE: 857 (100.0%)  *OK*

## Whittier CA 

- Total records: 2,000
- Schemas: 
    - accela: 2,000 (100.0%)
- STATUS_NORMALIZED not missing: 1,989 (99.4%)  *OK*
    - Active: 626 (31.5%)
        - FILE_DATE: 626 (100.0%)  *OK*
        - PERMIT_DATE: 543 (86.7%)  *OK*
        - FINAL_DATE: 2 (0.3%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 626 (100.0%)  *OK*
    - Final: 924 (46.5%)
        - FILE_DATE: 924 (100.0%)  *OK*
        - PERMIT_DATE: 820 (88.7%)  *OK*
        - FINAL_DATE: 822 (89.0%)  *OK*
        - PERMIT_OR_FILE_DATE: 924 (100.0%)  *OK*
    - Inactive: 205 (10.3%)
        - FILE_DATE: 205 (100.0%)  *OK*
        - PERMIT_DATE: 14 (6.8%)  **FAIL**
        - FINAL_DATE: 0 (0.0%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 205 (100.0%)  *OK*
    - In Review: 234 (11.8%)
        - FILE_DATE: 234 (100.0%)  *OK*
        - PERMIT_DATE: 1 (0.4%)  **FAIL**
        - FINAL_DATE: 3 (1.3%)  **FAIL**
        - PERMIT_OR_FILE_DATE: 234 (100.0%)  *OK*

## By data requirements

- Require FILE_DATE for all permits, PERMIT_DATE for Active and Final, FINAL_DATE for Final: 17 / 35 meet criteria
- Require PERMIT_OR_FILE_DATE for all permits, FINAL_DATE for Final: 24 / 35 meet criteria
- Require PERMIT_OR_FILE_DATE for all permits: 31 / 35 meet criteria



## Conclusion

- PERMIT_OR_FILE_DATE appears mostly usable. 
- FINAL_DATE appears usable only for some jurisdictions. 
- Need to investigate:
    - If and when PERMIT_DATE and FILE_DATE are interchangeable
    - If and when FINAL_DATE is available
    - Why certain dates are not available for certain jurisdictions

