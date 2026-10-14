"""Remove duplicates: flag contacts whose cleaned email was already seen."""

import pandas as pd
from hamilton.function_modifiers import tag


@tag(
    label="Skip duplicate emails",
    description="Skips a contact when an earlier contact has the same email, so only the first one is kept.",
    group="dedupe",
    app="Code",
)
def remove_duplicates(verify_email_format: pd.DataFrame) -> pd.DataFrame:
    df = verify_email_format.copy()
    active = df[df["_rejected_reason"].isna()]
    first_seen: dict[str, tuple[int, str]] = {}
    for index, row in active.iterrows():
        first_id, first_name = first_seen.setdefault(row["email"], (row["_row_id"], row["name"]))
        if first_id != row["_row_id"]:
            df.at[index, "_rejected_reason"] = f"Same email as row {first_id} ({first_name})"
    return df
