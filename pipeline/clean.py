"""Clean contacts: tidy up text, remove junk characters, check email format."""

import re

import pandas as pd
from hamilton.function_modifiers import tag

INVISIBLE_CHARS = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
EMAIL_PATTERN = re.compile(r"^[a-z0-9._%-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")


@tag(
    label="Tidy names and emails",
    description="Fixes spacing and capitals: removes extra spaces, lowercases emails and capitalises names.",
    group="clean",
    app="Code",
)
def normalize_strings(load_contacts: pd.DataFrame) -> pd.DataFrame:
    df = load_contacts.copy()
    for column in ("name", "email", "company"):
        df[column] = df[column].str.strip()
    df["email"] = df["email"].str.lower()
    df["name"] = df["name"].str.title()
    return df


@tag(
    label="Remove stray characters",
    description="Removes invisible characters, 'mailto:' prefixes and trailing punctuation from names and emails.",
    group="clean",
    app="Code",
)
def strip_unwanted_characters(normalize_strings: pd.DataFrame) -> pd.DataFrame:
    df = normalize_strings.copy()
    for column in ("name", "email", "company"):
        df[column] = df[column].str.replace(INVISIBLE_CHARS, "", regex=True).str.strip()
    df["email"] = df["email"].str.replace(r"^mailto:", "", regex=True)
    df["email"] = df["email"].str.rstrip(",.;: ")
    df["name"] = df["name"].str.rstrip(",.;: ")
    return df


def _email_problem(email: str) -> str | None:
    if not email:
        return "Email is empty"
    if "@" not in email:
        return "Email has no @ sign"
    if "+" in email:
        return "Email contains a '+' sign, which is not allowed"
    if not EMAIL_PATTERN.match(email):
        return "Email is not in a valid format"
    return None


@tag(
    label="Skip invalid emails",
    description="Skips contacts whose email is empty, has no @ sign, contains a '+' or is otherwise malformed.",
    group="clean",
    app="Code",
)
def verify_email_format(strip_unwanted_characters: pd.DataFrame) -> pd.DataFrame:
    df = strip_unwanted_characters.copy()
    active = df["_rejected_reason"].isna()
    problems = df.loc[active, "email"].map(_email_problem)
    df.loc[active, "_rejected_reason"] = problems
    return df
