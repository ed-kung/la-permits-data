"""Shared utilities for working with the permits dataset."""

import json
from typing import Union


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


def detect_schema(data: Union[dict, str]) -> str:
    """Classify a permit record's DATA JSON by platform schema.

    Parameters
    ----------
    data : dict or str
        Either a parsed JSON dict or a raw JSON string from the DATA column.

    Returns
    -------
    str
        One of ``'accela'``, ``'energov'``, or ``'custom'``.

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
    """
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
