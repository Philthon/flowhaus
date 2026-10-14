"""Export clean list: drop flagged contacts and write the final CSV."""

from pathlib import Path

import pandas as pd
from hamilton.function_modifiers import tag


@tag(
    label="Save clean list",
    description="Saves every contact that wasn't skipped to output/contacts_clean.csv.",
    group="export",
    app="CSV file",
)
def export_clean_list(remove_duplicates: pd.DataFrame, output_path: str) -> pd.DataFrame:
    df = remove_duplicates[remove_duplicates["_rejected_reason"].isna()].copy()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    df.drop(columns=["_row_id", "_rejected_reason"]).to_csv(output_path, index=False)
    return df
