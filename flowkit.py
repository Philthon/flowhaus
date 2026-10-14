"""Small helpers for writing flow steps (used by flows/*/steps/*.py).

Conventions every step follows:
- items travel as a pandas DataFrame with `_row_id` (stable id) and `_rejected_reason` (None = still active);
- steps never drop items: they set `_rejected_reason` to a short plain-English sentence ("skip");
- a step returns a new DataFrame (never edit the input in place).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pandas as pd

from connectors import ItemError


class Skip(Exception):
    """Raise inside an `update_items` function to skip that one item with a reason."""


def load_items(input_path: str) -> pd.DataFrame:
    """Read the flow's input (CSV or JSON list) and number the items."""
    path = Path(input_path)
    if path.suffix == ".json":
        df = pd.DataFrame(json.loads(path.read_text()))
    else:
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df.insert(0, "_row_id", range(1, len(df) + 1))
    df["_rejected_reason"] = None
    return df


def active(df: pd.DataFrame) -> pd.DataFrame:
    """Items that have not been skipped yet."""
    return df[df["_rejected_reason"].isna()]


def update_items(df: pd.DataFrame, fn: Callable[[dict], dict | None]) -> pd.DataFrame:
    """Call fn(item) for every active item and merge the dict it returns into that item.

    Raise Skip("reason") in fn to skip an item. A connector ItemError (e.g. page not found)
    also skips just that item. Anything else fails the whole step.
    """
    out = df.copy()
    out["_rejected_reason"] = out["_rejected_reason"].astype(object)
    for index, row in active(df).iterrows():
        try:
            updates = fn({k: v for k, v in row.items() if not k.startswith("_")}) or {}
        except (Skip, ItemError) as exc:
            out.at[index, "_rejected_reason"] = str(exc)
            continue
        for key, value in updates.items():
            if key not in out.columns:
                out[key] = None
            out[key] = out[key].astype(object)
            out.at[index, key] = value if not isinstance(value, (list, dict)) else json.dumps(value)
    return out


def skip_where(df: pd.DataFrame, mask: pd.Series, reason: str) -> pd.DataFrame:
    """Skip every active item where mask is True."""
    out = df.copy()
    out["_rejected_reason"] = out["_rejected_reason"].astype(object)
    out.loc[mask & out["_rejected_reason"].isna(), "_rejected_reason"] = reason
    return out
