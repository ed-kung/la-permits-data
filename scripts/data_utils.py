"""Shared utilities for working with the permits dataset."""

import json
import math
import re
import numpy as np
import time
from typing import Optional, Union

import pandas as pd

import os
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

ROOT_PATH = os.getenv("ROOT_PATH")
MY_DATA_PATH = os.getenv("MY_DATA_PATH")
RAW_DATA_PATH = os.getenv("RAW_DATA_PATH")
DEWEY_PATH = os.path.join(RAW_DATA_PATH, "dewey-downloads", "building-permits-united-states")

DEWEY_SUMMARY_FILEPATH = os.path.join(MY_DATA_PATH, "dewey_summary.parquet")

# -- Read data for one JURISDICTION/STATE -------------------------------------

def get_data_for_jurisdiction(jurisdiction, state, columns=None, n_records=None, rng=np.random.RandomState(42), verbose=True):
    summary_df = pd.read_parquet(DEWEY_SUMMARY_FILEPATH)
    files = summary_df.loc[(summary_df['JURISDICTION'] == jurisdiction) & (summary_df['STATE'] == state), 'FILENAME'].tolist()
    if len(files) == 0:
        return pd.DataFrame()
    total_records = summary_df.loc[(summary_df['JURISDICTION'] == jurisdiction) & (summary_df['STATE'] == state), 'COUNT'].sum()

    # Control sampling
    if n_records is None:
        frac = 1.0
    else:
        frac = n_records / total_records

    t0 = time.time()
    dfs = []
    for i, f in enumerate(files):
        dt = time.time() - t0
        if verbose:
            print(f"\rRetrieving data for {jurisdiction} {state} ... {i + 1}/{len(files)} files ... elapsed time {dt:.2f} seconds              ", end="", flush=True)
        temp_df = pd.read_parquet(os.path.join(DEWEY_PATH, f), columns=columns)
        temp_df = temp_df.loc[(temp_df['JURISDICTION'] == jurisdiction) & (temp_df['STATE'] == state)]
        temp_df = temp_df.sample(frac=frac, random_state=rng)
        dfs.append(temp_df)
    df = pd.concat(dfs).reset_index(drop=True)
    if verbose:
        print("")
    return df

# -- Read data for multiple JURISDICTION/STATE pairs -------------------------------------

def get_data_for_jurisdictions(jurisdictions, states, columns=None, n_records=None, rng=np.random.RandomState(42), verbose=True):
    dfs = []
    t0 = time.time()
    i = 0
    for jurisdiction, state in zip(jurisdictions, states):
        df = get_data_for_jurisdiction(jurisdiction, state, columns=columns, n_records=n_records, rng=rng, verbose=verbose)
        dfs.append(df)
        if verbose:
            dt = time.time() - t0
            print(f"{i+1}/{len(jurisdictions)} retrieved ... elapsed time: {dt:.2f} seconds")
    if verbose:
        print("")
    return pd.concat(dfs).reset_index(drop=True)

# -- Data quality assessment ---------------------------------------------------

STATUSES = ['Active', 'Final', 'Inactive', 'In Review']
DATE_CONCEPTS = ['FILE_DATE', 'PERMIT_DATE', 'FINAL_DATE', 'PERMIT_OR_FILE_DATE']
QUALITY_CONCEPTS = {
    "Require FILE_DATE for all permits, PERMIT_DATE for Active and Final, FINAL_DATE for Final": {
        "FILE_DATE": ["Active", "Final", "Inactive", "In Review"],
        "PERMIT_DATE": ["Active", "Final"],
        "FINAL_DATE": ["Final"]
    },
    "Require PERMIT_OR_FILE_DATE for all permits, FINAL_DATE for Final": {
        "PERMIT_OR_FILE_DATE": ["Active", "Final", "Inactive", "In Review"],
        "FINAL_DATE": ["Final"]
    },
    "Require PERMIT_OR_FILE_DATE for all permits": {
        "PERMIT_OR_FILE_DATE": ["Active", "Final", "Inactive", "In Review"]
    }
}

def assess_data_quality(df):
    df['PERMIT_OR_FILE_DATE'] = df['PERMIT_DATE'].fillna(df['FILE_DATE'])
    result = {}
    n_total = len(df)
    n_status_ok = (df['STATUS_NORMALIZED'].notna()).sum()
    pct_status_ok = n_status_ok / (n_total + 1e-6)
    result['n_total'] = n_total
    result['n_status_ok'] = n_status_ok
    result['pct_status_ok'] = pct_status_ok
    for status in STATUSES:
        result[f'status__{status}'] = {}
        n_status = (df['STATUS_NORMALIZED'] == status).sum()
        pct_status = n_status / (n_status_ok + 1e-6)
        result[f'status__{status}']['n_status'] = n_status
        result[f'status__{status}']['pct_status'] = pct_status
        for dc in DATE_CONCEPTS:
            result[f'status__{status}'][f'{dc}'] = {}
            n_ok = ((df['STATUS_NORMALIZED'] == status) & (df[dc].notna())).sum()
            pct_ok = n_ok / (n_status + 1e-6)
            result[f'status__{status}'][f'{dc}']['n_ok'] = n_ok
            result[f'status__{status}'][f'{dc}']['pct_ok'] = pct_ok
    return result

def data_quality_report(df, threshold=0.85):

    jurs_df = df[['JURISDICTION', 'STATE']].drop_duplicates().reset_index(drop=True)
    jurisdictions = jurs_df['JURISDICTION'].tolist()
    states = jurs_df['STATE'].tolist()

    md = ""
    results = {}
    for jurisdiction, state in zip(jurisdictions, states):

        # Header and get data
        md += f"## {jurisdiction} {state} \n\n"
        sub_df = df.loc[(df['JURISDICTION'] == jurisdiction) & (df['STATE'] == state)]
        if len(sub_df) == 0:
            md += f"**No permits data found for {jurisdiction} {state}**.\n\n"
            continue

        result = assess_data_quality(sub_df)
        results[(jurisdiction, state)] = result

        # Total records
        md += f"- Total records: {result['n_total']:,}\n"

        # Schemas
        if 'SCHEMA' in sub_df.columns:
            schemas = sub_df['SCHEMA'].unique().tolist()
            md += "- Schemas: \n"
            for schema in schemas:
                n_schema = (sub_df['SCHEMA'] == schema).sum()
                pct_schema = n_schema / (len(sub_df) + 1e-6)
                md += f"    - {schema}: {n_schema:,} ({pct_schema:.1%})\n"

        # STATUS_NORMALIZED
        okfail = "*OK*" if result['pct_status_ok'] >= threshold else "**FAIL**"
        md += f"- STATUS_NORMALIZED not missing: {result['n_status_ok']:,} ({result['pct_status_ok']:.1%})  {okfail}\n"

        # Date concepts by status
        for status in STATUSES:
            md += f"    - {status}: {result[f'status__{status}']['n_status']:,} ({result[f'status__{status}']['pct_status']:.1%})\n"
            for dc in DATE_CONCEPTS:
                okfail = "*OK*" if result[f'status__{status}'][f'{dc}']['pct_ok'] >= threshold else "**FAIL**"
                md += f"        - {dc}: {result[f'status__{status}'][f'{dc}']['n_ok']:,} ({result[f'status__{status}'][f'{dc}']['pct_ok']:.1%})  {okfail}\n"
        
        md += "\n"
    
    # By data requirements
    md += "## By data requirements\n\n"
    for concept, reqs in QUALITY_CONCEPTS.items():
        md += f"- {concept}: "
        n_usable = 0
        for jurisdiction, state in results.keys():
            result = results[(jurisdiction, state)]
            usable = True
            for dc, statuses in reqs.items():
                for status in statuses:
                    if result[f'status__{status}'][f'{dc}']['pct_ok'] < threshold:
                        usable = False
                        break
            if usable:
                n_usable += 1
        md += f"{n_usable:,} / {len(jurisdictions)} meet criteria\n"

    md += "\n"
    return md


# -- Schema detection ---------------------------------------------------------
#
# The raw DATA JSON across jurisdictions falls into three platform families,
# each identifiable by their top-level key structure:
#
#   accela     ~25 cities on Accela / CivicPlatform.  Canonical keys include
#              date, more_details, record_type, inspections, details, contacts,
#              search_data, tasks, fees_details, related_records, etc.
#
#   energov    ~4 cities on CityGovApp / Energov.  Keys include entity,
#              details, processing_status, fees, contacts.
#
#   custom     Everything else — each city has its own bespoke schema.

ACCELA_SIGNATURE = frozenset(
    {"date", "more_details", "record_type", "inspections", "details", "contacts"}
)

ENERGOV_SIGNATURE = frozenset(
    {"entity", "details", "processing_status", "fees", "contacts"}
)


def _is_missing(data) -> bool:
    """Return True for None / NaN (e.g. missing parquet DATA cells)."""
    if data is None:
        return True
    if isinstance(data, float) and math.isnan(data):
        return True
    return False


def detect_schema(data: Union[dict, str, None]) -> Optional[str]:
    """Classify a permit record's DATA JSON by platform schema.

    Parameters
    ----------
    data : dict, str, or None
        Either a parsed JSON dict or a raw JSON string from the DATA column.
        Missing values (``None`` / NaN) return ``None``.

    Returns
    -------
    str or None
        One of ``'accela'``, ``'energov'``, or ``'custom'``, or ``None`` when
        *data* is missing.

    Raises
    ------
    ValueError
        If *data* is a string that cannot be parsed as JSON, or if the parsed
        value is not a dict.

    Examples
    --------
    >>> detect_schema({"date": "2024-01-01", "more_details": {}, "record_type": "Building",
    ...                "inspections": [], "details": {}, "contacts": []})
    'accela'
    >>> detect_schema({"entity": {}, "details": {}, "processing_status": [],
    ...                "fees": [], "contacts": []})
    'energov'
    >>> detect_schema({"filings": [], "issuances": []})
    'custom'
    >>> detect_schema(None) is None
    True
    """
    if _is_missing(data):
        return None

    if isinstance(data, str):
        data = json.loads(data)

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object (dict), got {type(data).__name__}")

    keys = set(data.keys())

    if ACCELA_SIGNATURE <= keys:
        return "accela"

    if ENERGOV_SIGNATURE <= keys:
        return "energov"

    return "custom"


# -- Date field extraction ----------------------------------------------------

_DATE_KEY_RE = re.compile(r"date|time|status|action|complet|final", re.IGNORECASE)


def _is_date_key(key: str) -> bool:
    """Return True if *key* looks like it could hold date/time information."""
    return _DATE_KEY_RE.search(key) is not None


_DATE_SEPARATOR_RE = re.compile(r"[\-/\s]")


def _is_date_value(value) -> bool:
    """Return True if *value* is a scalar string convertible to a datetime.

    To avoid false positives on purely numeric strings (e.g. "0010", "42"),
    the value must contain at least one typical date separator (hyphen, slash,
    or whitespace) before parsing is attempted.
    """
    if not isinstance(value, str) or not value.strip():
        return False
    if not _DATE_SEPARATOR_RE.search(value):
        return False
    try:
        pd.to_datetime(value)
        return True
    except (ValueError, TypeError):
        return False


def extract_date_fields(data: Union[dict, str, None]) -> dict:
    """Extract every key that may indicate date/time information from *data*.

    Recursively walks the JSON structure (dicts and lists of dicts) and keeps
    keys that either (a) have a name containing ``'date'``, ``'time'``, etc.
    (case-insensitive), or (b) have a scalar string value that is convertible
    to a datetime via ``pd.to_datetime``.  Structural parent keys needed to
    reach matching keys are also preserved.

    When a matching key is found its value is preserved as-is (scalar, list,
    nested dict, etc.).  Non-matching keys are dropped unless they are
    ancestors of a matching key.

    Parameters
    ----------
    data : dict, str, or None
        Either a parsed JSON dict or a raw JSON string.  Missing values
        (``None`` / NaN) return ``{}``.

    Returns
    -------
    dict
        A pruned copy of *data* containing only date/time keys and the
        structural keys needed to reach them.  Returns ``{}`` if no
        date/time keys are found, or if *data* is missing.

    Examples
    --------
    >>> extract_date_fields({
    ...     "name": "John",
    ...     "filing_date": "2024-01-15",
    ...     "details": {
    ...         "color": "blue",
    ...         "issue_date": "2024-02-01",
    ...     },
    ...     "contacts": [{"name": "Jane"}],
    ... })
    {'filing_date': '2024-01-15', 'details': {'issue_date': '2024-02-01'}}
    >>> extract_date_fields(None)
    {}
    """
    if _is_missing(data):
        return {}

    if isinstance(data, str):
        data = json.loads(data)

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object (dict), got {type(data).__name__}")

    return _extract_from_dict(data)


def _extract_from_dict(d: dict) -> dict:
    result = {}
    for key, value in d.items():
        if _is_date_key(key) or _is_date_value(value):
            result[key] = value
        elif isinstance(value, dict):
            sub = _extract_from_dict(value)
            if sub:
                result[key] = sub
        elif isinstance(value, list):
            sub_list = _extract_from_list(value)
            if sub_list:
                result[key] = sub_list
    return result


def _extract_from_list(lst: list) -> list:
    result = []
    found_any = False
    for item in lst:
        if isinstance(item, dict):
            sub = _extract_from_dict(item)
            if sub:
                result.append(sub)
                found_any = True
        elif isinstance(item, list):
            sub_list = _extract_from_list(item)
            if sub_list:
                result.append(sub_list)
                found_any = True
    return result if found_any else []
