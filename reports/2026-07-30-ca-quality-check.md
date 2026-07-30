
# Data quality report for California jurisidictions

This report checks for data quality of 4 variables:
- STATUS_NORMALIZED (Active, Final, In Review, Inactive)
- FILE_DATE
- PERMIT_DATE
- FINAL_DATE

There are 250 total jurisidctions.

The quality check is performed after data repair rescripts are run for each jurisdiction. The data repair scripts check the provided data fields against the included raw JSON.


## FILE_DATE 

A jurisdiction was considered unusable if more than 20% of the permits had missing file dates.

21 out of 250 jurisdictions were considered unusable because of missing FILE_DATE.  

They account for 8.9% of the total permits in the data.

The jurisdictions are: Albany, Arroyo Grande, Calistoga, Compton, Contra Costa County, Emeryville, Fairfield, Goleta, Imperial, King City, Lathrop, Long Beach, Manteca, Marina, Mountain View, Pismo Beach, Sausalito, Truckee, Twentynine Palms, Union City, Willows


## STATUS_NORMALIZED

A jurisdiction was considered unusable if more than 20% of the permits had missing STATUS_NORMALIZED.

3 out of 250 jurisdictions were considered unusable because of missing STATUS_NORMALIZED.

They account for 0.4% of the total permits in the data.

The jurisdictions are: Humboldt County, Imperial, Inglewood


## TIMELINE MEASURABILITY

We define four concepts of timeline measurability:

- CONCEPT 1:
    - Active permits must have FILE_DATE, PERMIT_DATE
    - Final permits must have FILE_DATE, PERMIT_DATE, FINAL_DATE
- CONCEPT 2:
    - Active permits must have FILE_DATE, PERMIT_DATE
    - Final permits must have FILE_DATE, FINAL_DATE
- CONCEPT 3:
    - Active and final permits must have FILE_DATE, PERMIT_DATE
- CONCEPT 4:
    - Active and final permits must have FILE_DATE

A jurisdiction/year is considered to be "usable" with a concept if more than 75% of the permits with a FILE_DATE in that year satisfy the requirements for the concept. (Note that Concept 4 is always usable when FILE_DATE is available.)

Below is a table showing, for each range of years, the number of jurisdictions with usable years for each concept for that entire year range.

| Filing Year Range | CONCEPT_1 | CONCEPT_2 | CONCEPT_3 | CONCEPT_4 | 
| --- | --- | --- | --- | --- | 
| 2000-2025 | 46 | 54 | 52 | 128 | 
| 2001-2025 | 48 | 56 | 55 | 133 | 
| 2002-2025 | 52 | 60 | 58 | 138 | 
| 2003-2025 | 53 | 61 | 60 | 142 | 
| 2004-2025 | 56 | 65 | 64 | 143 | 
| 2005-2025 | 59 | 67 | 67 | 148 | 
| 2006-2025 | 60 | 69 | 68 | 153 | 
| 2007-2025 | 64 | 73 | 72 | 158 | 
| 2008-2025 | 67 | 76 | 74 | 162 | 
| 2009-2025 | 68 | 77 | 75 | 166 | 
| 2010-2025 | 71 | 82 | 80 | 177 | 
| 2011-2025 | 80 | 90 | 89 | 183 | 
| 2012-2025 | 83 | 93 | 91 | 185 | 
| 2013-2025 | 87 | 100 | 97 | 190 | 
| 2014-2025 | 93 | 106 | 101 | 195 | 
| 2015-2025 | 98 | 111 | 108 | 200 | 
| 2016-2025 | 102 | 117 | 114 | 207 | 
| 2017-2025 | 109 | 126 | 121 | 212 | 
| 2018-2025 | 118 | 135 | 132 | 218 | 
| 2019-2025 | 128 | 143 | 142 | 224 | 
| 2020-2025 | 133 | 150 | 149 | 225 | 
| 2021-2025 | 135 | 152 | 151 | 227 | 
| 2022-2025 | 142 | 160 | 156 | 229 | 
