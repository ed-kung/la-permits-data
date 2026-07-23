"""Shared utilities for working with the permits dataset."""

import json
import math
import re
from typing import Optional, Union

import pandas as pd


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


def _is_date_value(value) -> bool:
    """Return True if *value* is a scalar string convertible to a datetime."""
    if not isinstance(value, str) or not value.strip():
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
