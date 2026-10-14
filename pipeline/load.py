"""Load contacts: read the raw CSV and give every row a stable id."""

import pandas as pd
from hamilton.function_modifiers import tag


@tag(
    label="Load contacts",
    description="Gives you every contact from the file, numbered so each one can be followed through the flow.",
    group="load",
    app="CSV file",
)
def load_contacts(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    df.insert(0, "_row_id", range(1, len(df) + 1))
    df["_rejected_reason"] = None
    return df
