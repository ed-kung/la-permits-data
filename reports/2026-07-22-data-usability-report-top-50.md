
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

- Total permits: 45,664,385
- STATUS_NORMALIZED not missing: 41,647,686 (91.2%) - *OK*
    - Active: 6,885,908 (16.5%)
        - FILE_DATE non-missing: 6,261,610 (90.9%) [1994-2025]- *OK* 
        - PERMIT_DATE non-missing: 4,461,570 (64.8%) [1995-2025]- **CHECK** 
        - FINAL_DATE non-missing: 398,215 (5.8%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 6,831,974 (99.2%) [1995-2025]- *OK* 
    - Final: 27,738,202 (66.6%)
        - FILE_DATE non-missing: 24,539,609 (88.5%) [1985-2025]- *OK* 
        - PERMIT_DATE non-missing: 19,526,113 (70.4%) [1985-2025]- **CHECK** 
        - FINAL_DATE non-missing: 14,659,515 (52.8%) [1984-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 27,153,782 (97.9%) [1985-2025]- *OK* 
    - Inactive: 4,323,278 (10.4%)
        - FILE_DATE non-missing: 3,984,719 (92.2%) [1982-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,398,303 (55.5%) [1981-2024]- **CHECK** 
        - FINAL_DATE non-missing: 715,828 (16.6%) [1967-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 4,143,130 (95.8%) [1982-2025]- *OK* 
    - In Review: 2,700,298 (6.5%)
        - FILE_DATE non-missing: 2,349,580 (87.0%) [1995-2025]- *OK* 
        - PERMIT_DATE non-missing: 802,552 (29.7%) [1990-2025]- **CHECK** 
        - FINAL_DATE non-missing: 486,617 (18.0%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,608,570 (96.6%) [1994-2025]- *OK* 

## Los Angeles, CA

- Total permits: 37,488,984
- STATUS_NORMALIZED not missing: 34,659,887 (92.5%) - *OK*
    - Active: 5,985,910 (17.3%)
        - FILE_DATE non-missing: 5,047,036 (84.3%) [1993-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 4,064,695 (67.9%) [1992-2025]- **CHECK** 
        - FINAL_DATE non-missing: 321,106 (5.4%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 5,941,010 (99.2%) [1992-2025]- *OK* 
    - Final: 22,639,303 (65.3%)
        - FILE_DATE non-missing: 18,787,768 (83.0%) [1988-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 15,777,863 (69.7%) [1987-2024]- **CHECK** 
        - FINAL_DATE non-missing: 12,227,265 (54.0%) [1986-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 22,039,814 (97.4%) [1989-2025]- *OK* 
    - Inactive: 3,274,665 (9.4%)
        - FILE_DATE non-missing: 2,747,703 (83.9%) [1987-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,899,057 (58.0%) [1985-2024]- **CHECK** 
        - FINAL_DATE non-missing: 540,301 (16.5%) [1981-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 3,137,776 (95.8%) [1987-2025]- *OK* 
    - In Review: 2,760,009 (8.0%)
        - FILE_DATE non-missing: 2,215,149 (80.3%) [1996-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 822,428 (29.8%) [1991-2025]- **CHECK** 
        - FINAL_DATE non-missing: 447,734 (16.2%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,617,536 (94.8%) [1994-2025]- *OK* 

## Chicago, IL

- Total permits: 10,857,606
- STATUS_NORMALIZED not missing: 9,113,540 (83.9%) - **CHECK**
    - Active: 1,474,508 (16.2%)
        - FILE_DATE non-missing: 1,344,642 (91.2%) [1995-2025]- *OK* 
        - PERMIT_DATE non-missing: 936,493 (63.5%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 90,616 (6.1%) [1997-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,463,782 (99.3%) [1993-2025]- *OK* 
    - Final: 6,081,591 (66.7%)
        - FILE_DATE non-missing: 5,232,166 (86.0%) [1983-2025]- *OK* 
        - PERMIT_DATE non-missing: 4,304,339 (70.8%) [1983-2024]- **CHECK** 
        - FINAL_DATE non-missing: 3,444,649 (56.6%) [1982-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 5,938,526 (97.6%) [1983-2025]- *OK* 
    - Inactive: 934,842 (10.3%)
        - FILE_DATE non-missing: 863,694 (92.4%) [1981-2025]- *OK* 
        - PERMIT_DATE non-missing: 547,022 (58.5%) [1981-2024]- **CHECK** 
        - FINAL_DATE non-missing: 169,116 (18.1%) [1981-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 901,787 (96.5%) [1981-2025]- *OK* 
    - In Review: 622,599 (6.8%)
        - FILE_DATE non-missing: 533,867 (85.7%) [1993-2025]- *OK* 
        - PERMIT_DATE non-missing: 161,339 (25.9%) [1991-2025]- **CHECK** 
        - FINAL_DATE non-missing: 92,381 (14.8%) [1991-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 586,925 (94.3%) [1993-2025]- *OK* 

## Houston, TX

- Total permits: 8,890,171
- STATUS_NORMALIZED not missing: 8,176,355 (92.0%) - *OK*
    - Active: 2,563,577 (31.4%)
        - FILE_DATE non-missing: 1,127,802 (44.0%) [1994-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 2,069,343 (80.7%) [1998-2025]- **CHECK** 
        - FINAL_DATE non-missing: 59,381 (2.3%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,544,390 (99.3%) [1997-2025]- *OK* 
    - Final: 4,528,307 (55.4%)
        - FILE_DATE non-missing: 4,246,276 (93.8%) [1990-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,772,265 (61.2%) [1989-2024]- **CHECK** 
        - FINAL_DATE non-missing: 2,095,014 (46.3%) [1971-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 4,486,884 (99.1%) [1989-2025]- *OK* 
    - Inactive: 547,416 (6.7%)
        - FILE_DATE non-missing: 521,457 (95.3%) [1991-2025]- *OK* 
        - PERMIT_DATE non-missing: 268,558 (49.1%) [1988-2024]- **CHECK** 
        - FINAL_DATE non-missing: 68,514 (12.5%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 533,563 (97.5%) [1990-2025]- *OK* 
    - In Review: 537,055 (6.6%)
        - FILE_DATE non-missing: 495,989 (92.4%) [1900-2025]- *OK* 
        - PERMIT_DATE non-missing: 147,060 (27.4%) [1-2025]- **CHECK** 
        - FINAL_DATE non-missing: 95,462 (17.8%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 518,344 (96.5%) [1900-2025]- *OK* 

## Phoenix, AZ

- Total permits: 18,958,614
- STATUS_NORMALIZED not missing: 17,117,357 (90.3%) - *OK*
    - Active: 2,984,164 (17.4%)
        - FILE_DATE non-missing: 2,542,306 (85.2%) [1982-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,052,568 (68.8%) [1986-2025]- **CHECK** 
        - FINAL_DATE non-missing: 187,625 (6.3%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,955,256 (99.0%) [1986-2025]- *OK* 
    - Final: 10,637,792 (62.1%)
        - FILE_DATE non-missing: 9,467,053 (89.0%) [1989-2025]- *OK* 
        - PERMIT_DATE non-missing: 6,973,369 (65.6%) [1987-2025]- **CHECK** 
        - FINAL_DATE non-missing: 5,363,361 (50.4%) [1985-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 10,312,111 (96.9%) [1989-2025]- *OK* 
    - Inactive: 1,691,517 (9.9%)
        - FILE_DATE non-missing: 1,342,210 (79.3%) [1987-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,010,622 (59.7%) [1986-2024]- **CHECK** 
        - FINAL_DATE non-missing: 269,667 (15.9%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,606,965 (95.0%) [1987-2025]- *OK* 
    - In Review: 1,803,884 (10.5%)
        - FILE_DATE non-missing: 968,143 (53.7%) [1995-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 936,767 (51.9%) [1990-2025]- **CHECK** 
        - FINAL_DATE non-missing: 710,615 (39.4%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,695,011 (94.0%) [1992-2025]- *OK* 

## Philadelphia, PA

- Total permits: 7,803,090
- STATUS_NORMALIZED not missing: 7,176,432 (92.0%) - *OK*
    - Active: 1,147,498 (16.0%)
        - FILE_DATE non-missing: 993,643 (86.6%) [1997-2025]- *OK* 
        - PERMIT_DATE non-missing: 730,409 (63.7%) [1996-2025]- **CHECK** 
        - FINAL_DATE non-missing: 60,297 (5.3%) [2000-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,144,213 (99.7%) [1997-2025]- *OK* 
    - Final: 4,939,041 (68.8%)
        - FILE_DATE non-missing: 3,717,291 (75.3%) [1984-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 3,694,226 (74.8%) [1985-2024]- **CHECK** 
        - FINAL_DATE non-missing: 3,324,746 (67.3%) [1983-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 4,833,930 (97.9%) [1985-2025]- *OK* 
    - Inactive: 668,571 (9.3%)
        - FILE_DATE non-missing: 570,541 (85.3%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 439,767 (65.8%) [1983-2024]- **CHECK** 
        - FINAL_DATE non-missing: 194,324 (29.1%) [1981-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 661,971 (99.0%) [1984-2025]- *OK* 
    - In Review: 421,322 (5.9%)
        - FILE_DATE non-missing: 315,459 (74.9%) [1900-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 152,466 (36.2%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 125,129 (29.7%) [1995-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 413,990 (98.3%) [1991-2025]- *OK* 

## San Antonio, TX

- Total permits: 28,699,236
- STATUS_NORMALIZED not missing: 26,118,515 (91.0%) - *OK*
    - Active: 5,686,089 (21.8%)
        - FILE_DATE non-missing: 4,509,266 (79.3%) [1993-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 3,616,135 (63.6%) [1992-2025]- **CHECK** 
        - FINAL_DATE non-missing: 359,589 (6.3%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 5,644,612 (99.3%) [1992-2025]- *OK* 
    - Final: 16,164,758 (61.9%)
        - FILE_DATE non-missing: 14,655,031 (90.7%) [1989-2025]- *OK* 
        - PERMIT_DATE non-missing: 9,853,350 (61.0%) [1988-2025]- **CHECK** 
        - FINAL_DATE non-missing: 7,598,371 (47.0%) [1986-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 15,753,504 (97.5%) [1989-2025]- *OK* 
    - Inactive: 2,356,994 (9.0%)
        - FILE_DATE non-missing: 2,176,080 (92.3%) [1986-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,241,009 (52.7%) [1985-2024]- **CHECK** 
        - FINAL_DATE non-missing: 320,775 (13.6%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,279,892 (96.7%) [1986-2025]- *OK* 
    - In Review: 1,910,674 (7.3%)
        - FILE_DATE non-missing: 1,701,777 (89.1%) [1900-2025]- *OK* 
        - PERMIT_DATE non-missing: 580,399 (30.4%) [1-2025]- **CHECK** 
        - FINAL_DATE non-missing: 327,002 (17.1%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,828,659 (95.7%) [1900-2025]- *OK* 

## San Diego, CA

- Total permits: 33,705,527
- STATUS_NORMALIZED not missing: 30,846,316 (91.5%) - *OK*
    - Active: 5,372,416 (17.4%)
        - FILE_DATE non-missing: 4,659,825 (86.7%) [1993-2025]- *OK* 
        - PERMIT_DATE non-missing: 3,627,229 (67.5%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 347,016 (6.5%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 5,313,480 (98.9%) [1993-2025]- *OK* 
    - Final: 19,824,069 (64.3%)
        - FILE_DATE non-missing: 17,596,609 (88.8%) [1991-2025]- *OK* 
        - PERMIT_DATE non-missing: 13,636,521 (68.8%) [1990-2025]- **CHECK** 
        - FINAL_DATE non-missing: 10,990,942 (55.4%) [1988-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 19,164,156 (96.7%) [1991-2025]- *OK* 
    - Inactive: 3,046,553 (9.9%)
        - FILE_DATE non-missing: 2,742,075 (90.0%) [1988-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,699,907 (55.8%) [1984-2024]- **CHECK** 
        - FINAL_DATE non-missing: 561,165 (18.4%) [1979-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,927,723 (96.1%) [1987-2025]- *OK* 
    - In Review: 2,603,278 (8.4%)
        - FILE_DATE non-missing: 2,080,543 (79.9%) [1993-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 907,014 (34.8%) [1990-2025]- **CHECK** 
        - FINAL_DATE non-missing: 521,864 (20.0%) [1899-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,488,900 (95.6%) [1993-2025]- *OK* 

## Dallas, TX

- Total permits: 9,699,110
- STATUS_NORMALIZED not missing: 9,046,335 (93.3%) - *OK*
    - Active: 1,557,651 (17.2%)
        - FILE_DATE non-missing: 1,342,914 (86.2%) [1998-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,054,787 (67.7%) [1998-2025]- **CHECK** 
        - FINAL_DATE non-missing: 123,919 (8.0%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,551,253 (99.6%) [1997-2025]- *OK* 
    - Final: 5,855,403 (64.7%)
        - FILE_DATE non-missing: 5,293,891 (90.4%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 4,081,805 (69.7%) [1984-2025]- **CHECK** 
        - FINAL_DATE non-missing: 3,223,058 (55.0%) [1984-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 5,778,296 (98.7%) [1985-2025]- *OK* 
    - Inactive: 997,514 (11.0%)
        - FILE_DATE non-missing: 949,250 (95.2%) [1985-2025]- *OK* 
        - PERMIT_DATE non-missing: 535,853 (53.7%) [1983-2024]- **CHECK** 
        - FINAL_DATE non-missing: 309,943 (31.1%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 981,951 (98.4%) [1984-2025]- *OK* 
    - In Review: 635,767 (7.0%)
        - FILE_DATE non-missing: 603,709 (95.0%) [2000-2025]- *OK* 
        - PERMIT_DATE non-missing: 191,567 (30.1%) [1-2025]- **CHECK** 
        - FINAL_DATE non-missing: 117,303 (18.5%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 620,958 (97.7%) [1995-2025]- *OK* 

## Jacksonville, FL

- Total permits: 49,968,652
- STATUS_NORMALIZED not missing: 45,718,347 (91.5%) - *OK*
    - Active: 6,931,903 (15.2%)
        - FILE_DATE non-missing: 6,188,568 (89.3%) [1994-2025]- *OK* 
        - PERMIT_DATE non-missing: 4,489,367 (64.8%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 406,269 (5.9%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 6,833,103 (98.6%) [1993-2025]- *OK* 
    - Final: 30,966,775 (67.7%)
        - FILE_DATE non-missing: 26,379,061 (85.2%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 22,093,668 (71.3%) [1984-2025]- **CHECK** 
        - FINAL_DATE non-missing: 17,425,172 (56.3%) [1983-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 30,329,125 (97.9%) [1984-2025]- *OK* 
    - Inactive: 4,835,704 (10.6%)
        - FILE_DATE non-missing: 4,345,687 (89.9%) [1983-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,807,987 (58.1%) [1981-2024]- **CHECK** 
        - FINAL_DATE non-missing: 841,790 (17.4%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 4,588,510 (94.9%) [1982-2025]- *OK* 
    - In Review: 2,983,965 (6.5%)
        - FILE_DATE non-missing: 2,478,497 (83.1%) [1996-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,011,958 (33.9%) [1989-2025]- **CHECK** 
        - FINAL_DATE non-missing: 734,211 (24.6%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,888,937 (96.8%) [1994-2025]- *OK* 

## Austin, TX

- Total permits: 38,252,449
- STATUS_NORMALIZED not missing: 34,997,230 (91.5%) - *OK*
    - Active: 5,155,236 (14.7%)
        - FILE_DATE non-missing: 4,547,621 (88.2%) [1992-2025]- *OK* 
        - PERMIT_DATE non-missing: 3,463,734 (67.2%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 361,320 (7.0%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 5,100,466 (98.9%) [1992-2025]- *OK* 
    - Final: 24,041,879 (68.7%)
        - FILE_DATE non-missing: 20,885,819 (86.9%) [1982-2025]- *OK* 
        - PERMIT_DATE non-missing: 17,576,170 (73.1%) [1982-2024]- **CHECK** 
        - FINAL_DATE non-missing: 14,886,637 (61.9%) [1982-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 23,377,434 (97.2%) [1982-2025]- *OK* 
    - Inactive: 3,659,679 (10.5%)
        - FILE_DATE non-missing: 3,274,188 (89.5%) [1981-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,278,048 (62.2%) [1980-2024]- **CHECK** 
        - FINAL_DATE non-missing: 817,785 (22.3%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 3,475,747 (95.0%) [1981-2025]- *OK* 
    - In Review: 2,140,436 (6.1%)
        - FILE_DATE non-missing: 1,732,325 (80.9%) [1995-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 761,456 (35.6%) [1991-2025]- **CHECK** 
        - FINAL_DATE non-missing: 428,188 (20.0%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,087,799 (97.5%) [1994-2025]- *OK* 

## Fort Worth, TX

- Total permits: 28,674,030
- STATUS_NORMALIZED not missing: 26,200,104 (91.4%) - *OK*
    - Active: 4,410,869 (16.8%)
        - FILE_DATE non-missing: 3,968,077 (90.0%) [1997-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,916,016 (66.1%) [1999-2025]- **CHECK** 
        - FINAL_DATE non-missing: 312,924 (7.1%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 4,370,687 (99.1%) [1997-2025]- *OK* 
    - Final: 17,169,767 (65.5%)
        - FILE_DATE non-missing: 15,490,666 (90.2%) [1986-2025]- *OK* 
        - PERMIT_DATE non-missing: 12,382,353 (72.1%) [1986-2025]- **CHECK** 
        - FINAL_DATE non-missing: 9,816,217 (57.2%) [1984-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 16,971,477 (98.8%) [1987-2025]- *OK* 
    - Inactive: 2,785,145 (10.6%)
        - FILE_DATE non-missing: 2,601,657 (93.4%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,616,040 (58.0%) [1981-2024]- **CHECK** 
        - FINAL_DATE non-missing: 516,249 (18.5%) [1972-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,706,239 (97.2%) [1983-2025]- *OK* 
    - In Review: 1,834,323 (7.0%)
        - FILE_DATE non-missing: 1,509,229 (82.3%) [1989-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 606,080 (33.0%) [1989-2025]- **CHECK** 
        - FINAL_DATE non-missing: 406,111 (22.1%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,771,109 (96.6%) [1989-2025]- *OK* 

## San Jose, CA

- Total permits: 12,519,152
- STATUS_NORMALIZED not missing: 11,632,796 (92.9%) - *OK*
    - Active: 2,182,086 (18.8%)
        - FILE_DATE non-missing: 1,948,405 (89.3%) [1992-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,454,089 (66.6%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 126,342 (5.8%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,171,658 (99.5%) [1991-2025]- *OK* 
    - Final: 7,406,884 (63.7%)
        - FILE_DATE non-missing: 6,850,521 (92.5%) [1990-2025]- *OK* 
        - PERMIT_DATE non-missing: 5,029,778 (67.9%) [1989-2025]- **CHECK** 
        - FINAL_DATE non-missing: 4,050,332 (54.7%) [1989-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 7,248,337 (97.9%) [1990-2025]- *OK* 
    - Inactive: 1,163,396 (10.0%)
        - FILE_DATE non-missing: 1,093,496 (94.0%) [1988-2025]- *OK* 
        - PERMIT_DATE non-missing: 634,332 (54.5%) [1984-2024]- **CHECK** 
        - FINAL_DATE non-missing: 183,995 (15.8%) [1980-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,126,226 (96.8%) [1987-2025]- *OK* 
    - In Review: 880,430 (7.6%)
        - FILE_DATE non-missing: 792,273 (90.0%) [1992-2025]- *OK* 
        - PERMIT_DATE non-missing: 265,775 (30.2%) [1974-2025]- **CHECK** 
        - FINAL_DATE non-missing: 138,865 (15.8%) [1955-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 846,249 (96.1%) [1992-2025]- *OK* 

## Columbus, OH

- Total permits: 22,869,024
- STATUS_NORMALIZED not missing: 21,122,016 (92.4%) - *OK*
    - Active: 3,722,652 (17.6%)
        - FILE_DATE non-missing: 3,197,849 (85.9%) [1993-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,616,989 (70.3%) [1997-2025]- **CHECK** 
        - FINAL_DATE non-missing: 166,757 (4.5%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 3,680,059 (98.9%) [1994-2025]- *OK* 
    - Final: 14,021,812 (66.4%)
        - FILE_DATE non-missing: 12,200,077 (87.0%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 9,962,556 (71.1%) [1985-2025]- **CHECK** 
        - FINAL_DATE non-missing: 7,683,181 (54.8%) [1984-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 13,644,929 (97.3%) [1984-2025]- *OK* 
    - Inactive: 2,083,498 (9.9%)
        - FILE_DATE non-missing: 1,927,671 (92.5%) [1983-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,215,156 (58.3%) [1981-2024]- **CHECK** 
        - FINAL_DATE non-missing: 321,936 (15.5%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,018,156 (96.9%) [1983-2025]- *OK* 
    - In Review: 1,294,054 (6.1%)
        - FILE_DATE non-missing: 1,204,381 (93.1%) [1997-2025]- *OK* 
        - PERMIT_DATE non-missing: 366,521 (28.3%) [1992-2025]- **CHECK** 
        - FINAL_DATE non-missing: 142,809 (11.0%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,246,581 (96.3%) [1997-2025]- *OK* 

## Charlotte, NC

- Total permits: 3,329,475
- STATUS_NORMALIZED not missing: 2,910,312 (87.4%) - *OK*
    - Active: 607,011 (20.9%)
        - FILE_DATE non-missing: 474,840 (78.2%) [1996-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 369,178 (60.8%) [2000-2025]- **CHECK** 
        - FINAL_DATE non-missing: 34,747 (5.7%) [1991-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 604,768 (99.6%) [1997-2025]- *OK* 
    - Final: 1,758,614 (60.4%)
        - FILE_DATE non-missing: 1,486,250 (84.5%) [1982-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,025,023 (58.3%) [1980-2024]- **CHECK** 
        - FINAL_DATE non-missing: 844,449 (48.0%) [1977-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,740,382 (99.0%) [1983-2025]- *OK* 
    - Inactive: 230,013 (7.9%)
        - FILE_DATE non-missing: 188,783 (82.1%) [1984-2024]- **CHECK** 
        - PERMIT_DATE non-missing: 141,253 (61.4%) [1983-2024]- **CHECK** 
        - FINAL_DATE non-missing: 31,823 (13.8%) [1981-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 223,020 (97.0%) [1985-2024]- *OK* 
    - In Review: 314,674 (10.8%)
        - FILE_DATE non-missing: 276,832 (88.0%) [1996-2025]- *OK* 
        - PERMIT_DATE non-missing: 107,566 (34.2%) [1995-2025]- **CHECK** 
        - FINAL_DATE non-missing: 26,204 (8.3%) [1992-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 304,003 (96.6%) [1995-2025]- *OK* 

## Indianapolis, IN

- Total permits: 12,197,712
- STATUS_NORMALIZED not missing: 11,548,559 (94.7%) - *OK*
    - Active: 2,198,388 (19.0%)
        - FILE_DATE non-missing: 1,897,138 (86.3%) [1994-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,533,631 (69.8%) [1994-2025]- **CHECK** 
        - FINAL_DATE non-missing: 110,785 (5.0%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,182,439 (99.3%) [1994-2025]- *OK* 
    - Final: 7,317,455 (63.4%)
        - FILE_DATE non-missing: 6,602,822 (90.2%) [1989-2025]- *OK* 
        - PERMIT_DATE non-missing: 4,790,180 (65.5%) [1987-2025]- **CHECK** 
        - FINAL_DATE non-missing: 3,639,443 (49.7%) [1985-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 7,146,127 (97.7%) [1990-2025]- *OK* 
    - Inactive: 1,097,640 (9.5%)
        - FILE_DATE non-missing: 966,552 (88.1%) [1988-2025]- *OK* 
        - PERMIT_DATE non-missing: 637,563 (58.1%) [1985-2024]- **CHECK** 
        - FINAL_DATE non-missing: 188,415 (17.2%) [1982-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,060,366 (96.6%) [1988-2025]- *OK* 
    - In Review: 935,076 (8.1%)
        - FILE_DATE non-missing: 734,402 (78.5%) [1995-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 301,671 (32.3%) [1994-2025]- **CHECK** 
        - FINAL_DATE non-missing: 98,725 (10.6%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 897,424 (96.0%) [1995-2025]- *OK* 

## San Francisco, CA

- Total permits: 8,832,055
- STATUS_NORMALIZED not missing: 8,100,711 (91.7%) - *OK*
    - Active: 1,398,568 (17.3%)
        - FILE_DATE non-missing: 1,173,190 (83.9%) [1990-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,038,784 (74.3%) [1980-2025]- **CHECK** 
        - FINAL_DATE non-missing: 101,930 (7.3%) [1991-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,383,010 (98.9%) [1990-2025]- *OK* 
    - Final: 5,292,042 (65.3%)
        - FILE_DATE non-missing: 4,461,364 (84.3%) [1985-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 3,734,630 (70.6%) [1985-2025]- **CHECK** 
        - FINAL_DATE non-missing: 3,037,751 (57.4%) [1984-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 5,093,248 (96.2%) [1985-2025]- *OK* 
    - Inactive: 713,401 (8.8%)
        - FILE_DATE non-missing: 641,317 (89.9%) [1983-2025]- *OK* 
        - PERMIT_DATE non-missing: 377,655 (52.9%) [1979-2024]- **CHECK** 
        - FINAL_DATE non-missing: 155,100 (21.7%) [1982-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 694,650 (97.4%) [1982-2025]- *OK* 
    - In Review: 696,700 (8.6%)
        - FILE_DATE non-missing: 584,933 (84.0%) [1991-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 276,180 (39.6%) [1990-2024]- **CHECK** 
        - FINAL_DATE non-missing: 192,427 (27.6%) [1899-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 671,652 (96.4%) [1991-2025]- *OK* 

## Seattle, WA

- Total permits: 23,048,415
- STATUS_NORMALIZED not missing: 21,473,132 (93.2%) - *OK*
    - Active: 3,470,633 (16.2%)
        - FILE_DATE non-missing: 3,033,346 (87.4%) [1998-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,310,460 (66.6%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 203,312 (5.9%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 3,454,861 (99.5%) [1996-2025]- *OK* 
    - Final: 14,382,161 (67.0%)
        - FILE_DATE non-missing: 12,943,674 (90.0%) [1987-2025]- *OK* 
        - PERMIT_DATE non-missing: 9,860,126 (68.6%) [1985-2025]- **CHECK** 
        - FINAL_DATE non-missing: 7,781,560 (54.1%) [1983-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 14,189,686 (98.7%) [1987-2025]- *OK* 
    - Inactive: 2,205,611 (10.3%)
        - FILE_DATE non-missing: 2,085,179 (94.5%) [1986-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,271,437 (57.6%) [1984-2024]- **CHECK** 
        - FINAL_DATE non-missing: 401,853 (18.2%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,150,530 (97.5%) [1986-2025]- *OK* 
    - In Review: 1,414,727 (6.6%)
        - FILE_DATE non-missing: 1,291,255 (91.3%) [1900-2025]- *OK* 
        - PERMIT_DATE non-missing: 382,572 (27.0%) [1900-2025]- **CHECK** 
        - FINAL_DATE non-missing: 212,691 (15.0%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,372,231 (97.0%) [1900-2025]- *OK* 

## Denver, CO

- Total permits: 29,780,205
- STATUS_NORMALIZED not missing: 27,691,169 (93.0%) - *OK*
    - Active: 4,878,340 (17.6%)
        - FILE_DATE non-missing: 4,235,562 (86.8%) [1992-2025]- *OK* 
        - PERMIT_DATE non-missing: 3,390,785 (69.5%) [1991-2025]- **CHECK** 
        - FINAL_DATE non-missing: 359,015 (7.4%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 4,852,650 (99.5%) [1991-2025]- *OK* 
    - Final: 17,749,524 (64.1%)
        - FILE_DATE non-missing: 15,706,614 (88.5%) [1990-2025]- *OK* 
        - PERMIT_DATE non-missing: 12,066,286 (68.0%) [1989-2025]- **CHECK** 
        - FINAL_DATE non-missing: 8,708,297 (49.1%) [1988-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 17,424,439 (98.2%) [1990-2025]- *OK* 
    - Inactive: 2,616,608 (9.4%)
        - FILE_DATE non-missing: 2,287,861 (87.4%) [1988-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,505,603 (57.5%) [1986-2024]- **CHECK** 
        - FINAL_DATE non-missing: 426,999 (16.3%) [1978-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,535,172 (96.9%) [1987-2025]- *OK* 
    - In Review: 2,446,697 (8.8%)
        - FILE_DATE non-missing: 1,986,939 (81.2%) [1995-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 908,331 (37.1%) [1989-2025]- **CHECK** 
        - FINAL_DATE non-missing: 498,768 (20.4%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,348,488 (96.0%) [1993-2025]- *OK* 

## Oklahoma City, OK

- Total permits: 20,099,886
- STATUS_NORMALIZED not missing: 18,393,134 (91.5%) - *OK*
    - Active: 3,117,857 (17.0%)
        - FILE_DATE non-missing: 2,781,969 (89.2%) [1993-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,044,043 (65.6%) [1992-2025]- **CHECK** 
        - FINAL_DATE non-missing: 166,863 (5.4%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 3,097,811 (99.4%) [1991-2025]- *OK* 
    - Final: 12,188,565 (66.3%)
        - FILE_DATE non-missing: 10,877,855 (89.2%) [1991-2025]- *OK* 
        - PERMIT_DATE non-missing: 8,165,873 (67.0%) [1990-2025]- **CHECK** 
        - FINAL_DATE non-missing: 6,452,298 (52.9%) [1990-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 11,941,447 (98.0%) [1990-2025]- *OK* 
    - Inactive: 1,674,382 (9.1%)
        - FILE_DATE non-missing: 1,468,841 (87.7%) [1988-2025]- *OK* 
        - PERMIT_DATE non-missing: 943,603 (56.4%) [1987-2024]- **CHECK** 
        - FINAL_DATE non-missing: 251,088 (15.0%) [1983-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,601,294 (95.6%) [1988-2025]- *OK* 
    - In Review: 1,412,330 (7.7%)
        - FILE_DATE non-missing: 1,162,046 (82.3%) [1900-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 436,045 (30.9%) [1990-2025]- **CHECK** 
        - FINAL_DATE non-missing: 278,528 (19.7%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,352,213 (95.7%) [1900-2025]- *OK* 

## Nashville, TN

- Total permits: 33,338,205
- STATUS_NORMALIZED not missing: 30,465,298 (91.4%) - *OK*
    - Active: 5,216,935 (17.1%)
        - FILE_DATE non-missing: 4,492,003 (86.1%) [1992-2025]- *OK* 
        - PERMIT_DATE non-missing: 3,419,721 (65.6%) [1990-2025]- **CHECK** 
        - FINAL_DATE non-missing: 335,687 (6.4%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 5,164,217 (99.0%) [1990-2025]- *OK* 
    - Final: 19,375,414 (63.6%)
        - FILE_DATE non-missing: 17,249,370 (89.0%) [1988-2025]- *OK* 
        - PERMIT_DATE non-missing: 13,136,527 (67.8%) [1987-2025]- **CHECK** 
        - FINAL_DATE non-missing: 10,410,044 (53.7%) [1985-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 19,026,999 (98.2%) [1988-2025]- *OK* 
    - Inactive: 3,157,997 (10.4%)
        - FILE_DATE non-missing: 2,906,644 (92.0%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,779,712 (56.4%) [1984-2024]- **CHECK** 
        - FINAL_DATE non-missing: 515,058 (16.3%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 3,064,112 (97.0%) [1984-2025]- *OK* 
    - In Review: 2,714,952 (8.9%)
        - FILE_DATE non-missing: 2,258,396 (83.2%) [1994-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,220,659 (45.0%) [1990-2025]- **CHECK** 
        - FINAL_DATE non-missing: 594,213 (21.9%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,610,105 (96.1%) [1993-2025]- *OK* 

## Washington, DC

- Total permits: 5,245,259
- STATUS_NORMALIZED not missing: 4,945,779 (94.3%) - *OK*
    - Active: 1,396,803 (28.2%)
        - FILE_DATE non-missing: 757,753 (54.2%) [1996-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,093,254 (78.3%) [1991-2025]- **CHECK** 
        - FINAL_DATE non-missing: 79,743 (5.7%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,394,570 (99.8%) [1991-2025]- *OK* 
    - Final: 2,850,600 (57.6%)
        - FILE_DATE non-missing: 2,473,029 (86.8%) [1989-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,843,298 (64.7%) [1988-2025]- **CHECK** 
        - FINAL_DATE non-missing: 1,222,570 (42.9%) [1985-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,817,434 (98.8%) [1989-2025]- *OK* 
    - Inactive: 432,905 (8.8%)
        - FILE_DATE non-missing: 413,705 (95.6%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 233,991 (54.1%) [1985-2024]- **CHECK** 
        - FINAL_DATE non-missing: 57,576 (13.3%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 423,684 (97.9%) [1984-2025]- *OK* 
    - In Review: 265,471 (5.4%)
        - FILE_DATE non-missing: 250,144 (94.2%) [1997-2025]- *OK* 
        - PERMIT_DATE non-missing: 53,508 (20.2%) [1900-2025]- **CHECK** 
        - FINAL_DATE non-missing: 24,960 (9.4%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 256,803 (96.7%) [1995-2025]- *OK* 

## El Paso, TX

- Total permits: 9,546,834
- STATUS_NORMALIZED not missing: 8,833,252 (92.5%) - *OK*
    - Active: 1,959,244 (22.2%)
        - FILE_DATE non-missing: 1,472,473 (75.2%) [1995-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,438,693 (73.4%) [1998-2025]- **CHECK** 
        - FINAL_DATE non-missing: 123,495 (6.3%) [1992-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,940,446 (99.0%) [1996-2025]- *OK* 
    - Final: 5,489,895 (62.2%)
        - FILE_DATE non-missing: 5,016,687 (91.4%) [1990-2025]- *OK* 
        - PERMIT_DATE non-missing: 3,332,646 (60.7%) [1990-2025]- **CHECK** 
        - FINAL_DATE non-missing: 2,511,706 (45.8%) [1989-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 5,342,871 (97.3%) [1990-2025]- *OK* 
    - Inactive: 779,762 (8.8%)
        - FILE_DATE non-missing: 743,927 (95.4%) [1991-2025]- *OK* 
        - PERMIT_DATE non-missing: 422,044 (54.1%) [1988-2024]- **CHECK** 
        - FINAL_DATE non-missing: 112,024 (14.4%) [1965-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 760,937 (97.6%) [1990-2025]- *OK* 
    - In Review: 604,351 (6.8%)
        - FILE_DATE non-missing: 561,354 (92.9%) [1994-2025]- *OK* 
        - PERMIT_DATE non-missing: 184,636 (30.6%) [1992-2025]- **CHECK** 
        - FINAL_DATE non-missing: 99,100 (16.4%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 578,049 (95.6%) [1994-2025]- *OK* 

## Las Vegas, NV

*Note: The best match for Las Vegas, NV in the permits data was North Las Vegas, NV*.

- Total permits: 1,605,569
- STATUS_NORMALIZED not missing: 1,543,469 (96.1%) - *OK*
    - Active: 341,292 (22.1%)
        - FILE_DATE non-missing: 286,750 (84.0%) [2002-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 256,842 (75.3%) [2004-2025]- **CHECK** 
        - FINAL_DATE non-missing: 5,195 (1.5%) [2002-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 338,653 (99.2%) [2002-2025]- *OK* 
    - Final: 911,414 (59.0%)
        - FILE_DATE non-missing: 827,090 (90.7%) [1986-2025]- *OK* 
        - PERMIT_DATE non-missing: 657,730 (72.2%) [1986-2024]- **CHECK** 
        - FINAL_DATE non-missing: 436,905 (47.9%) [1985-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 876,196 (96.1%) [1986-2025]- *OK* 
    - Inactive: 179,364 (11.6%)
        - FILE_DATE non-missing: 164,972 (92.0%) [1986-2025]- *OK* 
        - PERMIT_DATE non-missing: 122,989 (68.6%) [1985-2024]- **CHECK** 
        - FINAL_DATE non-missing: 19,689 (11.0%) [1982-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 168,393 (93.9%) [1986-2025]- *OK* 
    - In Review: 111,399 (7.2%)
        - FILE_DATE non-missing: 107,368 (96.4%) [2000-2025]- *OK* 
        - PERMIT_DATE non-missing: 18,467 (16.6%) [2000-2025]- **CHECK** 
        - FINAL_DATE non-missing: 7,664 (6.9%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 107,577 (96.6%) [2000-2025]- *OK* 

## Boston, MA

- Total permits: 5,393,128
- STATUS_NORMALIZED not missing: 4,968,506 (92.1%) - *OK*
    - Active: 681,322 (13.7%)
        - FILE_DATE non-missing: 569,169 (83.5%) [1998-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 425,830 (62.5%) [1996-2025]- **CHECK** 
        - FINAL_DATE non-missing: 41,858 (6.1%) [2000-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 676,000 (99.2%) [1996-2025]- *OK* 
    - Final: 3,151,106 (63.4%)
        - FILE_DATE non-missing: 2,314,356 (73.4%) [1982-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 2,324,382 (73.8%) [1984-2025]- **CHECK** 
        - FINAL_DATE non-missing: 2,046,963 (65.0%) [1983-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 3,023,171 (95.9%) [1983-2025]- *OK* 
    - Inactive: 504,718 (10.2%)
        - FILE_DATE non-missing: 464,174 (92.0%) [1975-2025]- *OK* 
        - PERMIT_DATE non-missing: 286,466 (56.8%) [1965-2024]- **CHECK** 
        - FINAL_DATE non-missing: 136,692 (27.1%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 486,728 (96.4%) [1972-2025]- *OK* 
    - In Review: 631,360 (12.7%)
        - FILE_DATE non-missing: 205,778 (32.6%) [1992-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 464,174 (73.5%) [1995-2025]- **CHECK** 
        - FINAL_DATE non-missing: 376,068 (59.6%) [1-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 625,579 (99.1%) [1996-2025]- *OK* 

## Detroit, MI

- Total permits: 544,768
- STATUS_NORMALIZED not missing: 520,527 (95.6%) - *OK*
    - Active: 139,934 (26.9%)
        - FILE_DATE non-missing: 83,241 (59.5%) [1992-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 96,788 (69.2%) [1992-2025]- **CHECK** 
        - FINAL_DATE non-missing: 53,868 (38.5%) [2006-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 139,838 (99.9%) [1993-2025]- *OK* 
    - Final: 300,313 (57.7%)
        - FILE_DATE non-missing: 287,129 (95.6%) [1983-2025]- *OK* 
        - PERMIT_DATE non-missing: 177,578 (59.1%) [1982-2025]- **CHECK** 
        - FINAL_DATE non-missing: 166,913 (55.6%) [1982-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 289,196 (96.3%) [1983-2025]- *OK* 
    - Inactive: 43,414 (8.3%)
        - FILE_DATE non-missing: 41,760 (96.2%) [1982-2025]- *OK* 
        - PERMIT_DATE non-missing: 27,534 (63.4%) [1982-2025]- **CHECK** 
        - FINAL_DATE non-missing: 7,689 (17.7%) [1981-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 43,121 (99.3%) [1983-2025]- *OK* 
    - In Review: 36,866 (7.1%)
        - FILE_DATE non-missing: 35,919 (97.4%) [1992-2025]- *OK* 
        - PERMIT_DATE non-missing: 5,388 (14.6%) [2010-2025]- **CHECK** 
        - FINAL_DATE non-missing: 219 (0.6%) [2003-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 35,932 (97.5%) [1992-2025]- *OK* 

## Portland, OR

- Total permits: 10,655,673
- STATUS_NORMALIZED not missing: 10,087,857 (94.7%) - *OK*
    - Active: 1,805,816 (17.9%)
        - FILE_DATE non-missing: 1,516,974 (84.0%) [1992-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,229,764 (68.1%) [1994-2025]- **CHECK** 
        - FINAL_DATE non-missing: 87,353 (4.8%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,786,931 (99.0%) [1993-2025]- *OK* 
    - Final: 6,721,132 (66.6%)
        - FILE_DATE non-missing: 6,200,800 (92.3%) [1990-2025]- *OK* 
        - PERMIT_DATE non-missing: 4,529,869 (67.4%) [1989-2025]- **CHECK** 
        - FINAL_DATE non-missing: 3,854,761 (57.4%) [1985-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 6,624,913 (98.6%) [1989-2025]- *OK* 
    - Inactive: 958,786 (9.5%)
        - FILE_DATE non-missing: 908,238 (94.7%) [1987-2025]- *OK* 
        - PERMIT_DATE non-missing: 609,033 (63.5%) [1983-2024]- **CHECK** 
        - FINAL_DATE non-missing: 139,963 (14.6%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 941,892 (98.2%) [1985-2025]- *OK* 
    - In Review: 602,123 (6.0%)
        - FILE_DATE non-missing: 554,768 (92.1%) [1995-2025]- *OK* 
        - PERMIT_DATE non-missing: 143,948 (23.9%) [1-2025]- **CHECK** 
        - FINAL_DATE non-missing: 91,375 (15.2%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 582,879 (96.8%) [1994-2025]- *OK* 

## Louisville, KY

*Note: The best match for Louisville, KY in the permits data was Louisville-Jefferson County, KY*.

- Total permits: 8,860,613
- STATUS_NORMALIZED not missing: 8,262,235 (93.2%) - *OK*
    - Active: 1,475,968 (17.9%)
        - FILE_DATE non-missing: 1,245,650 (84.4%) [1998-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 987,402 (66.9%) [1997-2025]- **CHECK** 
        - FINAL_DATE non-missing: 79,369 (5.4%) [2002-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,467,089 (99.4%) [1997-2025]- *OK* 
    - Final: 5,036,487 (61.0%)
        - FILE_DATE non-missing: 4,494,250 (89.2%) [1989-2025]- *OK* 
        - PERMIT_DATE non-missing: 3,441,731 (68.3%) [1988-2025]- **CHECK** 
        - FINAL_DATE non-missing: 2,462,420 (48.9%) [1987-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 4,953,496 (98.4%) [1989-2025]- *OK* 
    - Inactive: 1,108,378 (13.4%)
        - FILE_DATE non-missing: 1,060,971 (95.7%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 710,144 (64.1%) [1985-2023]- **CHECK** 
        - FINAL_DATE non-missing: 260,608 (23.5%) [1980-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,086,090 (98.0%) [1984-2025]- *OK* 
    - In Review: 641,402 (7.8%)
        - FILE_DATE non-missing: 552,449 (86.1%) [1999-2025]- *OK* 
        - PERMIT_DATE non-missing: 173,254 (27.0%) [1995-2025]- **CHECK** 
        - FINAL_DATE non-missing: 132,321 (20.6%) [1-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 627,960 (97.9%) [1995-2025]- *OK* 

## Memphis, TN

- Total permits: 14,483,777
- STATUS_NORMALIZED not missing: 13,217,588 (91.3%) - *OK*
    - Active: 2,417,194 (18.3%)
        - FILE_DATE non-missing: 2,012,305 (83.2%) [1994-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,586,943 (65.7%) [1999-2025]- **CHECK** 
        - FINAL_DATE non-missing: 124,772 (5.2%) [1999-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,382,686 (98.6%) [1995-2025]- *OK* 
    - Final: 8,621,752 (65.2%)
        - FILE_DATE non-missing: 7,745,757 (89.8%) [1987-2025]- *OK* 
        - PERMIT_DATE non-missing: 5,620,329 (65.2%) [1986-2025]- **CHECK** 
        - FINAL_DATE non-missing: 4,514,456 (52.4%) [1986-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 8,258,318 (95.8%) [1987-2025]- *OK* 
    - Inactive: 1,354,460 (10.2%)
        - FILE_DATE non-missing: 1,240,717 (91.6%) [1986-2025]- *OK* 
        - PERMIT_DATE non-missing: 803,066 (59.3%) [1983-2024]- **CHECK** 
        - FINAL_DATE non-missing: 188,363 (13.9%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,297,089 (95.8%) [1986-2025]- *OK* 
    - In Review: 824,182 (6.2%)
        - FILE_DATE non-missing: 734,856 (89.2%) [2000-2025]- *OK* 
        - PERMIT_DATE non-missing: 194,458 (23.6%) [1-2025]- **CHECK** 
        - FINAL_DATE non-missing: 119,408 (14.5%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 796,002 (96.6%) [1994-2025]- *OK* 

## Baltimore, MD

- Total permits: 8,341,431
- STATUS_NORMALIZED not missing: 7,320,957 (87.8%) - *OK*
    - Active: 1,137,157 (15.5%)
        - FILE_DATE non-missing: 1,048,099 (92.2%) [1998-2025]- *OK* 
        - PERMIT_DATE non-missing: 750,421 (66.0%) [1999-2025]- **CHECK** 
        - FINAL_DATE non-missing: 51,519 (4.5%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,125,906 (99.0%) [1997-2025]- *OK* 
    - Final: 4,601,791 (62.9%)
        - FILE_DATE non-missing: 4,192,622 (91.1%) [1990-2025]- *OK* 
        - PERMIT_DATE non-missing: 3,125,888 (67.9%) [1990-2025]- **CHECK** 
        - FINAL_DATE non-missing: 2,201,185 (47.8%) [1987-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 4,415,362 (95.9%) [1990-2025]- *OK* 
    - Inactive: 1,003,072 (13.7%)
        - FILE_DATE non-missing: 941,801 (93.9%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 479,577 (47.8%) [1981-2025]- **CHECK** 
        - FINAL_DATE non-missing: 110,058 (11.0%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 980,622 (97.8%) [1984-2025]- *OK* 
    - In Review: 578,937 (7.9%)
        - FILE_DATE non-missing: 538,212 (93.0%) [1999-2025]- *OK* 
        - PERMIT_DATE non-missing: 214,420 (37.0%) [1992-2025]- **CHECK** 
        - FINAL_DATE non-missing: 108,317 (18.7%) [1899-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 552,992 (95.5%) [1998-2025]- *OK* 

## Milwaukee, WI

- Total permits: 30,661,168
- STATUS_NORMALIZED not missing: 28,521,044 (93.0%) - *OK*
    - Active: 5,481,489 (19.2%)
        - FILE_DATE non-missing: 4,427,111 (80.8%) [1992-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 3,600,032 (65.7%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 349,743 (6.4%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 5,429,812 (99.1%) [1992-2025]- *OK* 
    - Final: 18,259,577 (64.0%)
        - FILE_DATE non-missing: 16,198,679 (88.7%) [1989-2025]- *OK* 
        - PERMIT_DATE non-missing: 11,222,103 (61.5%) [1987-2025]- **CHECK** 
        - FINAL_DATE non-missing: 8,681,462 (47.5%) [1987-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 17,792,939 (97.4%) [1989-2025]- *OK* 
    - Inactive: 2,635,421 (9.2%)
        - FILE_DATE non-missing: 2,350,736 (89.2%) [1986-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,396,403 (53.0%) [1985-2024]- **CHECK** 
        - FINAL_DATE non-missing: 386,949 (14.7%) [1981-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,526,705 (95.9%) [1986-2025]- *OK* 
    - In Review: 2,144,557 (7.5%)
        - FILE_DATE non-missing: 1,874,530 (87.4%) [1994-2025]- *OK* 
        - PERMIT_DATE non-missing: 588,440 (27.4%) [1-2025]- **CHECK** 
        - FINAL_DATE non-missing: 401,850 (18.7%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,050,992 (95.6%) [1993-2025]- *OK* 

## Albuquerque, NM

- Total permits: 3,619,210
- STATUS_NORMALIZED not missing: 3,165,653 (87.5%) - *OK*
    - Active: 490,920 (15.5%)
        - FILE_DATE non-missing: 431,163 (87.8%) [1963-2025]- *OK* 
        - PERMIT_DATE non-missing: 343,451 (70.0%) [1962-2025]- **CHECK** 
        - FINAL_DATE non-missing: 20,944 (4.3%) [1994-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 489,593 (99.7%) [1964-2025]- *OK* 
    - Final: 1,920,007 (60.7%)
        - FILE_DATE non-missing: 1,746,383 (91.0%) [1987-2024]- *OK* 
        - PERMIT_DATE non-missing: 1,347,693 (70.2%) [1986-2024]- **CHECK** 
        - FINAL_DATE non-missing: 1,103,509 (57.5%) [1986-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,872,860 (97.5%) [1987-2024]- *OK* 
    - Inactive: 390,100 (12.3%)
        - FILE_DATE non-missing: 330,072 (84.6%) [1998-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 249,928 (64.1%) [1994-2024]- **CHECK** 
        - FINAL_DATE non-missing: 118,680 (30.4%) [1996-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 378,070 (96.9%) [1995-2025]- *OK* 
    - In Review: 364,626 (11.5%)
        - FILE_DATE non-missing: 245,899 (67.4%) [2001-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 169,836 (46.6%) [1995-2025]- **CHECK** 
        - FINAL_DATE non-missing: 53,912 (14.8%) [1900-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 352,594 (96.7%) [1996-2025]- *OK* 

## Tucson, AZ

- Total permits: 6,195,614
- STATUS_NORMALIZED not missing: 5,647,828 (91.2%) - *OK*
    - Active: 940,187 (16.6%)
        - FILE_DATE non-missing: 811,552 (86.3%) [1993-2025]- *OK* 
        - PERMIT_DATE non-missing: 637,736 (67.8%) [1998-2025]- **CHECK** 
        - FINAL_DATE non-missing: 56,447 (6.0%) [1988-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 935,570 (99.5%) [1993-2025]- *OK* 
    - Final: 3,716,439 (65.8%)
        - FILE_DATE non-missing: 3,253,015 (87.5%) [1993-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,364,806 (63.6%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 1,919,009 (51.6%) [1993-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 3,614,250 (97.3%) [1994-2025]- *OK* 
    - Inactive: 571,166 (10.1%)
        - FILE_DATE non-missing: 513,169 (89.8%) [1990-2025]- *OK* 
        - PERMIT_DATE non-missing: 268,450 (47.0%) [1990-2024]- **CHECK** 
        - FINAL_DATE non-missing: 95,904 (16.8%) [1985-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 544,420 (95.3%) [1990-2025]- *OK* 
    - In Review: 420,036 (7.4%)
        - FILE_DATE non-missing: 383,273 (91.2%) [1996-2025]- *OK* 
        - PERMIT_DATE non-missing: 107,474 (25.6%) [1992-2025]- **CHECK** 
        - FINAL_DATE non-missing: 71,758 (17.1%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 398,391 (94.8%) [1995-2025]- *OK* 

## Fresno, CA

- Total permits: 5,901,186
- STATUS_NORMALIZED not missing: 5,658,776 (95.9%) - *OK*
    - Active: 975,308 (17.2%)
        - FILE_DATE non-missing: 893,264 (91.6%) [1996-2025]- *OK* 
        - PERMIT_DATE non-missing: 675,482 (69.3%) [1991-2025]- **CHECK** 
        - FINAL_DATE non-missing: 29,838 (3.1%) [2001-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 967,554 (99.2%) [1993-2025]- *OK* 
    - Final: 3,729,674 (65.9%)
        - FILE_DATE non-missing: 3,388,106 (90.8%) [1993-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,499,909 (67.0%) [1993-2024]- **CHECK** 
        - FINAL_DATE non-missing: 1,772,136 (47.5%) [1994-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 3,683,673 (98.8%) [1993-2025]- *OK* 
    - Inactive: 476,092 (8.4%)
        - FILE_DATE non-missing: 427,637 (89.8%) [1992-2025]- *OK* 
        - PERMIT_DATE non-missing: 242,281 (50.9%) [1991-2024]- **CHECK** 
        - FINAL_DATE non-missing: 54,839 (11.5%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 454,696 (95.5%) [1992-2025]- *OK* 
    - In Review: 477,702 (8.4%)
        - FILE_DATE non-missing: 436,179 (91.3%) [1993-2025]- *OK* 
        - PERMIT_DATE non-missing: 136,035 (28.5%) [1989-2025]- **CHECK** 
        - FINAL_DATE non-missing: 72,610 (15.2%) [1899-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 458,944 (96.1%) [1993-2025]- *OK* 

## Sacramento, CA

- Total permits: 10,832,655
- STATUS_NORMALIZED not missing: 10,159,952 (93.8%) - *OK*
    - Active: 1,708,478 (16.8%)
        - FILE_DATE non-missing: 1,441,994 (84.4%) [1989-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,177,607 (68.9%) [1988-2025]- **CHECK** 
        - FINAL_DATE non-missing: 175,458 (10.3%) [1900-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,701,107 (99.6%) [1989-2025]- *OK* 
    - Final: 6,493,920 (63.9%)
        - FILE_DATE non-missing: 5,736,206 (88.3%) [1990-2025]- *OK* 
        - PERMIT_DATE non-missing: 4,347,524 (66.9%) [1990-2025]- **CHECK** 
        - FINAL_DATE non-missing: 3,194,346 (49.2%) [1990-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 6,355,226 (97.9%) [1990-2025]- *OK* 
    - Inactive: 1,048,700 (10.3%)
        - FILE_DATE non-missing: 934,353 (89.1%) [1996-2025]- *OK* 
        - PERMIT_DATE non-missing: 595,002 (56.7%) [1993-2024]- **CHECK** 
        - FINAL_DATE non-missing: 165,464 (15.8%) [1984-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,022,192 (97.5%) [1994-2025]- *OK* 
    - In Review: 908,854 (8.9%)
        - FILE_DATE non-missing: 692,771 (76.2%) [1991-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 393,923 (43.3%) [1989-2025]- **CHECK** 
        - FINAL_DATE non-missing: 149,072 (16.4%) [1-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 879,797 (96.8%) [1991-2025]- *OK* 

## Mesa, AZ

- Total permits: 6,907,233
- STATUS_NORMALIZED not missing: 6,174,549 (89.4%) - *OK*
    - Active: 943,641 (15.3%)
        - FILE_DATE non-missing: 830,598 (88.0%) [1998-2025]- *OK* 
        - PERMIT_DATE non-missing: 593,949 (62.9%) [2000-2025]- **CHECK** 
        - FINAL_DATE non-missing: 52,495 (5.6%) [2000-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 930,340 (98.6%) [1998-2025]- *OK* 
    - Final: 4,221,875 (68.4%)
        - FILE_DATE non-missing: 3,466,495 (82.1%) [1984-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 3,083,743 (73.0%) [1984-2025]- **CHECK** 
        - FINAL_DATE non-missing: 2,220,941 (52.6%) [1983-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 4,075,759 (96.5%) [1984-2025]- *OK* 
    - Inactive: 598,343 (9.7%)
        - FILE_DATE non-missing: 511,343 (85.5%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 344,361 (57.6%) [1981-2024]- **CHECK** 
        - FINAL_DATE non-missing: 117,409 (19.6%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 545,348 (91.1%) [1983-2025]- *OK* 
    - In Review: 410,690 (6.7%)
        - FILE_DATE non-missing: 333,034 (81.1%) [2000-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 131,997 (32.1%) [1995-2025]- **CHECK** 
        - FINAL_DATE non-missing: 123,012 (30.0%) [1-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 405,174 (98.7%) [2000-2025]- *OK* 

## Kansas City, MO

- Total permits: 13,224,788
- STATUS_NORMALIZED not missing: 12,430,456 (94.0%) - *OK*
    - Active: 2,161,587 (17.4%)
        - FILE_DATE non-missing: 1,925,355 (89.1%) [1994-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,481,658 (68.5%) [1994-2025]- **CHECK** 
        - FINAL_DATE non-missing: 101,355 (4.7%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,144,483 (99.2%) [1994-2025]- *OK* 
    - Final: 8,236,532 (66.3%)
        - FILE_DATE non-missing: 7,323,572 (88.9%) [1987-2025]- *OK* 
        - PERMIT_DATE non-missing: 5,686,493 (69.0%) [1985-2025]- **CHECK** 
        - FINAL_DATE non-missing: 4,699,201 (57.1%) [1984-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 7,994,259 (97.1%) [1987-2025]- *OK* 
    - Inactive: 1,254,482 (10.1%)
        - FILE_DATE non-missing: 1,171,589 (93.4%) [1983-2025]- *OK* 
        - PERMIT_DATE non-missing: 729,671 (58.2%) [1982-2025]- **CHECK** 
        - FINAL_DATE non-missing: 228,075 (18.2%) [1977-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,224,129 (97.6%) [1983-2025]- *OK* 
    - In Review: 777,855 (6.3%)
        - FILE_DATE non-missing: 719,260 (92.5%) [2000-2025]- *OK* 
        - PERMIT_DATE non-missing: 229,513 (29.5%) [1997-2025]- **CHECK** 
        - FINAL_DATE non-missing: 94,756 (12.2%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 744,441 (95.7%) [2000-2025]- *OK* 

## Atlanta, GA

- Total permits: 25,279,054
- STATUS_NORMALIZED not missing: 23,336,808 (92.3%) - *OK*
    - Active: 4,140,475 (17.7%)
        - FILE_DATE non-missing: 3,639,625 (87.9%) [1987-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,817,345 (68.0%) [1992-2025]- **CHECK** 
        - FINAL_DATE non-missing: 245,909 (5.9%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 4,091,790 (98.8%) [1990-2025]- *OK* 
    - Final: 15,131,100 (64.8%)
        - FILE_DATE non-missing: 13,271,377 (87.7%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 10,275,318 (67.9%) [1985-2024]- **CHECK** 
        - FINAL_DATE non-missing: 8,118,829 (53.7%) [1984-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 14,751,170 (97.5%) [1985-2025]- *OK* 
    - Inactive: 2,342,528 (10.0%)
        - FILE_DATE non-missing: 2,171,863 (92.7%) [1983-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,378,354 (58.8%) [1982-2024]- **CHECK** 
        - FINAL_DATE non-missing: 418,831 (17.9%) [1970-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,283,327 (97.5%) [1983-2025]- *OK* 
    - In Review: 1,722,705 (7.4%)
        - FILE_DATE non-missing: 1,558,125 (90.4%) [1993-2025]- *OK* 
        - PERMIT_DATE non-missing: 449,985 (26.1%) [1972-2025]- **CHECK** 
        - FINAL_DATE non-missing: 243,419 (14.1%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,660,273 (96.4%) [1992-2025]- *OK* 

## Omaha, NE

- Total permits: 15,022,002
- STATUS_NORMALIZED not missing: 13,791,975 (91.8%) - *OK*
    - Active: 3,049,756 (22.1%)
        - FILE_DATE non-missing: 2,725,298 (89.4%) [1995-2025]- *OK* 
        - PERMIT_DATE non-missing: 2,086,301 (68.4%) [1995-2025]- **CHECK** 
        - FINAL_DATE non-missing: 92,950 (3.0%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 3,031,683 (99.4%) [1995-2025]- *OK* 
    - Final: 8,432,950 (61.1%)
        - FILE_DATE non-missing: 7,343,011 (87.1%) [1990-2025]- *OK* 
        - PERMIT_DATE non-missing: 4,947,664 (58.7%) [1989-2025]- **CHECK** 
        - FINAL_DATE non-missing: 4,062,026 (48.2%) [1986-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 8,111,089 (96.2%) [1990-2025]- *OK* 
    - Inactive: 1,254,955 (9.1%)
        - FILE_DATE non-missing: 1,125,055 (89.6%) [1986-2025]- *OK* 
        - PERMIT_DATE non-missing: 649,164 (51.7%) [1980-2025]- **CHECK** 
        - FINAL_DATE non-missing: 168,845 (13.5%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,208,799 (96.3%) [1985-2025]- *OK* 
    - In Review: 1,054,314 (7.6%)
        - FILE_DATE non-missing: 830,246 (78.7%) [1999-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 358,007 (34.0%) [1994-2025]- **CHECK** 
        - FINAL_DATE non-missing: 146,935 (13.9%) [1-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,022,873 (97.0%) [1996-2025]- *OK* 

## Colorado Springs, CO

*Note: The best match for Colorado Springs, CO in the permits data was El Paso County, CO*.

- Total permits: 20,333,393
- STATUS_NORMALIZED not missing: 18,168,640 (89.4%) - *OK*
    - Active: 2,742,868 (15.1%)
        - FILE_DATE non-missing: 2,342,705 (85.4%) [1994-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,890,566 (68.9%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 115,598 (4.2%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,712,033 (98.9%) [1993-2025]- *OK* 
    - Final: 12,484,788 (68.7%)
        - FILE_DATE non-missing: 9,709,734 (77.8%) [1987-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 8,623,675 (69.1%) [1986-2024]- **CHECK** 
        - FINAL_DATE non-missing: 7,343,250 (58.8%) [1986-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 12,021,415 (96.3%) [1986-2025]- *OK* 
    - Inactive: 1,760,950 (9.7%)
        - FILE_DATE non-missing: 1,584,730 (90.0%) [1983-2025]- *OK* 
        - PERMIT_DATE non-missing: 990,715 (56.3%) [1981-2024]- **CHECK** 
        - FINAL_DATE non-missing: 273,728 (15.5%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,723,388 (97.9%) [1983-2025]- *OK* 
    - In Review: 1,180,034 (6.5%)
        - FILE_DATE non-missing: 963,842 (81.7%) [1995-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 433,648 (36.7%) [1991-2025]- **CHECK** 
        - FINAL_DATE non-missing: 297,639 (25.2%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,133,056 (96.0%) [1994-2025]- *OK* 

## Raleigh, NC

- Total permits: 13,339,732
- STATUS_NORMALIZED not missing: 12,520,963 (93.9%) - *OK*
    - Active: 2,229,780 (17.8%)
        - FILE_DATE non-missing: 1,977,120 (88.7%) [1996-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,597,137 (71.6%) [1995-2025]- **CHECK** 
        - FINAL_DATE non-missing: 140,586 (6.3%) [1997-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,214,797 (99.3%) [1995-2025]- *OK* 
    - Final: 7,993,634 (63.8%)
        - FILE_DATE non-missing: 7,352,156 (92.0%) [1988-2025]- *OK* 
        - PERMIT_DATE non-missing: 5,652,447 (70.7%) [1987-2024]- **CHECK** 
        - FINAL_DATE non-missing: 4,632,256 (57.9%) [1987-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 7,856,051 (98.3%) [1988-2025]- *OK* 
    - Inactive: 1,323,199 (10.6%)
        - FILE_DATE non-missing: 1,244,461 (94.0%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 782,610 (59.1%) [1983-2024]- **CHECK** 
        - FINAL_DATE non-missing: 255,199 (19.3%) [1977-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,298,169 (98.1%) [1984-2025]- *OK* 
    - In Review: 974,350 (7.8%)
        - FILE_DATE non-missing: 871,575 (89.5%) [1998-2025]- *OK* 
        - PERMIT_DATE non-missing: 346,065 (35.5%) [1991-2025]- **CHECK** 
        - FINAL_DATE non-missing: 229,127 (23.5%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 948,187 (97.3%) [1995-2025]- *OK* 

## Long Beach, CA

- Total permits: 2,029,531
- STATUS_NORMALIZED not missing: 1,737,993 (85.6%) - *OK*
    - Active: 265,047 (15.3%)
        - FILE_DATE non-missing: 220,677 (83.3%) [1992-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 121,849 (46.0%) [1994-2025]- **CHECK** 
        - FINAL_DATE non-missing: 51,203 (19.3%) [1989-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 231,195 (87.2%) [1992-2025]- *OK* 
    - Final: 1,178,926 (67.8%)
        - FILE_DATE non-missing: 974,989 (82.7%) [1988-2024]- **CHECK** 
        - PERMIT_DATE non-missing: 728,513 (61.8%) [1988-2024]- **CHECK** 
        - FINAL_DATE non-missing: 654,724 (55.5%) [1992-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,020,164 (86.5%) [1988-2024]- *OK* 
    - Inactive: 192,154 (11.1%)
        - FILE_DATE non-missing: 154,812 (80.6%) [1987-2024]- **CHECK** 
        - PERMIT_DATE non-missing: 87,401 (45.5%) [1987-2024]- **CHECK** 
        - FINAL_DATE non-missing: 34,597 (18.0%) [1994-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 160,340 (83.4%) [1987-2024]- **CHECK** 
    - In Review: 101,866 (5.9%)
        - FILE_DATE non-missing: 79,568 (78.1%) [1993-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 27,603 (27.1%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 31,380 (30.8%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 82,333 (80.8%) [1993-2025]- **CHECK** 

## Virginia Beach, VA

- Total permits: 13,531,808
- STATUS_NORMALIZED not missing: 12,601,912 (93.1%) - *OK*
    - Active: 1,985,248 (15.8%)
        - FILE_DATE non-missing: 1,816,427 (91.5%) [1990-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,366,082 (68.8%) [1986-2025]- **CHECK** 
        - FINAL_DATE non-missing: 137,261 (6.9%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,980,538 (99.8%) [1989-2025]- *OK* 
    - Final: 8,396,281 (66.6%)
        - FILE_DATE non-missing: 7,470,928 (89.0%) [1984-2025]- *OK* 
        - PERMIT_DATE non-missing: 6,039,826 (71.9%) [1984-2025]- **CHECK** 
        - FINAL_DATE non-missing: 4,835,630 (57.6%) [1983-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 8,298,854 (98.8%) [1984-2025]- *OK* 
    - Inactive: 1,361,524 (10.8%)
        - FILE_DATE non-missing: 1,257,006 (92.3%) [1983-2025]- *OK* 
        - PERMIT_DATE non-missing: 770,476 (56.6%) [1982-2024]- **CHECK** 
        - FINAL_DATE non-missing: 208,819 (15.3%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,313,868 (96.5%) [1983-2025]- *OK* 
    - In Review: 858,859 (6.8%)
        - FILE_DATE non-missing: 743,108 (86.5%) [1996-2025]- *OK* 
        - PERMIT_DATE non-missing: 317,996 (37.0%) [1991-2025]- **CHECK** 
        - FINAL_DATE non-missing: 204,916 (23.9%) [1899-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 843,591 (98.2%) [1995-2025]- *OK* 

## Miami, FL

- Total permits: 2,529,301
- STATUS_NORMALIZED not missing: 2,384,256 (94.3%) - *OK*
    - Active: 418,000 (17.5%)
        - FILE_DATE non-missing: 344,303 (82.4%) [1994-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 260,061 (62.2%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 10,883 (2.6%) [2005-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 416,574 (99.7%) [1995-2025]- *OK* 
    - Final: 1,628,603 (68.3%)
        - FILE_DATE non-missing: 1,348,539 (82.8%) [1993-2024]- **CHECK** 
        - PERMIT_DATE non-missing: 1,142,035 (70.1%) [1993-2024]- **CHECK** 
        - FINAL_DATE non-missing: 904,616 (55.5%) [1992-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,602,486 (98.4%) [1992-2024]- *OK* 
    - Inactive: 189,518 (7.9%)
        - FILE_DATE non-missing: 163,004 (86.0%) [1999-2025]- *OK* 
        - PERMIT_DATE non-missing: 99,395 (52.4%) [1994-2024]- **CHECK** 
        - FINAL_DATE non-missing: 20,291 (10.7%) [1997-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 184,558 (97.4%) [1996-2024]- *OK* 
    - In Review: 148,135 (6.2%)
        - FILE_DATE non-missing: 124,911 (84.3%) [2000-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 42,956 (29.0%) [1995-2025]- **CHECK** 
        - FINAL_DATE non-missing: 20,493 (13.8%) [1995-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 143,457 (96.8%) [1997-2025]- *OK* 

## Oakland, CA

- Total permits: 11,230,402
- STATUS_NORMALIZED not missing: 10,493,445 (93.4%) - *OK*
    - Active: 2,127,343 (20.3%)
        - FILE_DATE non-missing: 1,931,897 (90.8%) [1992-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,329,374 (62.5%) [1995-2025]- **CHECK** 
        - FINAL_DATE non-missing: 88,374 (4.2%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,112,711 (99.3%) [1992-2025]- *OK* 
    - Final: 6,507,183 (62.0%)
        - FILE_DATE non-missing: 6,009,971 (92.4%) [1990-2025]- *OK* 
        - PERMIT_DATE non-missing: 4,364,442 (67.1%) [1989-2025]- **CHECK** 
        - FINAL_DATE non-missing: 3,079,425 (47.3%) [1989-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 6,399,664 (98.3%) [1990-2025]- *OK* 
    - Inactive: 1,145,306 (10.9%)
        - FILE_DATE non-missing: 1,066,288 (93.1%) [1992-2025]- *OK* 
        - PERMIT_DATE non-missing: 610,607 (53.3%) [1987-2024]- **CHECK** 
        - FINAL_DATE non-missing: 122,848 (10.7%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,119,759 (97.8%) [1990-2025]- *OK* 
    - In Review: 713,613 (6.8%)
        - FILE_DATE non-missing: 652,454 (91.4%) [1996-2025]- *OK* 
        - PERMIT_DATE non-missing: 188,293 (26.4%) [1991-2025]- **CHECK** 
        - FINAL_DATE non-missing: 91,408 (12.8%) [1899-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 697,415 (97.7%) [1995-2025]- *OK* 

## Minneapolis, MN

- Total permits: 2,746,951
- STATUS_NORMALIZED not missing: 2,523,035 (91.8%) - *OK*
    - Active: 338,090 (13.4%)
        - FILE_DATE non-missing: 281,279 (83.2%) [2002-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 245,813 (72.7%) [2004-2025]- **CHECK** 
        - FINAL_DATE non-missing: 8,571 (2.5%) [1993-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 336,672 (99.6%) [2003-2025]- *OK* 
    - Final: 1,817,404 (72.0%)
        - FILE_DATE non-missing: 1,494,301 (82.2%) [1984-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 1,378,926 (75.9%) [1984-2025]- **CHECK** 
        - FINAL_DATE non-missing: 1,208,592 (66.5%) [1985-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,778,801 (97.9%) [1984-2025]- *OK* 
    - Inactive: 229,918 (9.1%)
        - FILE_DATE non-missing: 214,512 (93.3%) [1983-2024]- *OK* 
        - PERMIT_DATE non-missing: 118,964 (51.7%) [1982-2024]- **CHECK** 
        - FINAL_DATE non-missing: 25,428 (11.1%) [1981-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 224,752 (97.8%) [1983-2025]- *OK* 
    - In Review: 137,623 (5.5%)
        - FILE_DATE non-missing: 110,957 (80.6%) [2001-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 42,337 (30.8%) [2000-2025]- **CHECK** 
        - FINAL_DATE non-missing: 3,529 (2.6%) [2005-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 134,610 (97.8%) [2001-2025]- *OK* 

## Tulsa, OK

- Total permits: 4,435,349
- STATUS_NORMALIZED not missing: 4,071,310 (91.8%) - *OK*
    - Active: 684,564 (16.8%)
        - FILE_DATE non-missing: 621,651 (90.8%) [1992-2025]- *OK* 
        - PERMIT_DATE non-missing: 450,683 (65.8%) [1993-2025]- **CHECK** 
        - FINAL_DATE non-missing: 70,092 (10.2%) [1999-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 676,703 (98.9%) [1991-2025]- *OK* 
    - Final: 2,730,722 (67.1%)
        - FILE_DATE non-missing: 2,575,549 (94.3%) [1987-2025]- *OK* 
        - PERMIT_DATE non-missing: 1,911,381 (70.0%) [1985-2025]- **CHECK** 
        - FINAL_DATE non-missing: 1,556,948 (57.0%) [1985-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 2,718,643 (99.6%) [1986-2025]- *OK* 
    - Inactive: 420,265 (10.3%)
        - FILE_DATE non-missing: 379,377 (90.3%) [1986-2025]- *OK* 
        - PERMIT_DATE non-missing: 220,484 (52.5%) [1982-2024]- **CHECK** 
        - FINAL_DATE non-missing: 104,490 (24.9%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 390,319 (92.9%) [1985-2025]- *OK* 
    - In Review: 235,759 (5.8%)
        - FILE_DATE non-missing: 203,105 (86.1%) [2001-2025]- *OK* 
        - PERMIT_DATE non-missing: 59,140 (25.1%) [1998-2025]- **CHECK** 
        - FINAL_DATE non-missing: 39,509 (16.8%) [1-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 230,477 (97.8%) [2001-2025]- *OK* 

## Bakersfield, CA

- Total permits: 1,631,232
- STATUS_NORMALIZED not missing: 1,431,848 (87.8%) - *OK*
    - Active: 280,906 (19.6%)
        - FILE_DATE non-missing: 224,052 (79.8%) [1992-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 208,647 (74.3%) [2007-2025]- **CHECK** 
        - FINAL_DATE non-missing: 10,455 (3.7%) [2010-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 279,801 (99.6%) [1992-2025]- *OK* 
    - Final: 942,427 (65.8%)
        - FILE_DATE non-missing: 913,092 (96.9%) [1992-2024]- *OK* 
        - PERMIT_DATE non-missing: 617,287 (65.5%) [1992-2024]- **CHECK** 
        - FINAL_DATE non-missing: 555,385 (58.9%) [1992-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 934,988 (99.2%) [1991-2024]- *OK* 
    - Inactive: 126,448 (8.8%)
        - FILE_DATE non-missing: 117,146 (92.6%) [1992-2024]- *OK* 
        - PERMIT_DATE non-missing: 63,476 (50.2%) [1989-2024]- **CHECK** 
        - FINAL_DATE non-missing: 7,590 (6.0%) [1984-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 123,471 (97.6%) [1990-2024]- *OK* 
    - In Review: 82,067 (5.7%)
        - FILE_DATE non-missing: 65,386 (79.7%) [1992-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 30,160 (36.8%) [1991-2025]- **CHECK** 
        - FINAL_DATE non-missing: 13,131 (16.0%) [1992-2024]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 79,512 (96.9%) [1992-2025]- *OK* 

## Wichita, KS

**No permits data found for Wichita, KS**.


## Arlington, TX

- Total permits: 2,601,472
- STATUS_NORMALIZED not missing: 2,361,545 (90.8%) - *OK*
    - Active: 480,963 (20.4%)
        - FILE_DATE non-missing: 373,763 (77.7%) [2001-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 342,122 (71.1%) [2003-2025]- **CHECK** 
        - FINAL_DATE non-missing: 59,374 (12.3%) [2010-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 460,537 (95.8%) [2001-2025]- *OK* 
    - Final: 1,512,131 (64.0%)
        - FILE_DATE non-missing: 1,258,311 (83.2%) [1989-2025]- **CHECK** 
        - PERMIT_DATE non-missing: 988,312 (65.4%) [1988-2025]- **CHECK** 
        - FINAL_DATE non-missing: 748,439 (49.5%) [1988-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 1,448,963 (95.8%) [1988-2025]- *OK* 
    - Inactive: 214,539 (9.1%)
        - FILE_DATE non-missing: 191,555 (89.3%) [1992-2025]- *OK* 
        - PERMIT_DATE non-missing: 116,850 (54.5%) [1985-2025]- **CHECK** 
        - FINAL_DATE non-missing: 34,421 (16.0%) [1983-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 202,445 (94.4%) [1988-2025]- *OK* 
    - In Review: 153,912 (6.5%)
        - FILE_DATE non-missing: 146,169 (95.0%) [2000-2025]- *OK* 
        - PERMIT_DATE non-missing: 39,064 (25.4%) [2000-2025]- **CHECK** 
        - FINAL_DATE non-missing: 33,994 (22.1%) [1900-2025]- **CHECK** 
        - PERMIT_OR_FILE_DATE non-missing: 148,599 (96.5%) [2000-2025]- *OK* 


## By data requirements

- Require FILE_DATE for all statuses, PERMIT_DATE for all but 'In Review', FINAL_DATE for 'Final': 0 / 50 
- Require FILE_OR_PERMIT_DATE for all statuses, and FINAL_DATE for 'Final': 0 / 50 
- Require FILE_OR_PERMIT_DATE for all statuses: 48 / 50 



## Conclusion

PERMIT_OR_FILE_DATE appears mostly usable. However, FINAL_DATE does not. We need to investigate the availability of FINAL_DATE more. Does it depend on the jurisdiction and the permit types? Is there a subset of the data for which FINAL_DATE is mostly available?  Are there improvements to be made in extracting FINAL_DATE?

