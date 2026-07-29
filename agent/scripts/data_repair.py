"""State-agnostic dispatcher for jurisdiction-specific data repair scripts.

Resolves ``agent/scripts/{state}/data_repair_{state}_{slug}.py`` by convention
and delegates to that module's ``data_repair(df)``.
"""

from __future__ import annotations

import importlib.util
import re
import unicodedata
from pathlib import Path

import pandas as pd

_SCRIPTS_DIR = Path(__file__).resolve().parent


def _slugify(jurisdiction: str) -> str:
    """NFKD-normalize *jurisdiction* into a snake_case filename slug."""
    normalized = unicodedata.normalize("NFKD", jurisdiction)
    ascii_text = "".join(c for c in normalized if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower().strip())
    return slug.strip("_")


def _resolve_script_path(jurisdiction: str, state: str) -> Path:
    state_lower = state.lower().strip()
    slug = _slugify(jurisdiction)
    path = _SCRIPTS_DIR / state_lower / f"data_repair_{state_lower}_{slug}.py"
    if not path.is_file():
        raise FileNotFoundError(
            f"No data repair script for jurisdiction={jurisdiction!r} "
            f"state={state!r}; expected {path}"
        )
    return path


def _load_module(path: Path):
    module_name = f"data_repair_dispatch_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def data_repair(
    df: pd.DataFrame, jurisdiction: str, state: str
) -> pd.DataFrame:
    """Dispatch to the jurisdiction-specific ``data_repair`` implementation.

    Parameters
    ----------
    df : pd.DataFrame
        Jurisdiction slice to repair. The wrapper does not filter; the caller
        should pass rows for the given jurisdiction and state.
    jurisdiction : str
        Jurisdiction name (e.g. ``"Anaheim"``).
    state : str
        Two-letter state code (e.g. ``"CA"``).

    Returns
    -------
    pd.DataFrame
        Result of the jurisdiction script's ``data_repair(df)``.
    """
    path = _resolve_script_path(jurisdiction, state)
    module = _load_module(path)
    if not hasattr(module, "data_repair"):
        raise AttributeError(f"{path} has no data_repair function")
    return module.data_repair(df)
