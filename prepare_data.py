import pandas as pd
from pathlib import Path
from datetime import datetime

INTERESTING_COLUMNS = [
    "timestamp",
    "profession",
    "doctor_name",
    "available_date",
    "city",
    "address",
]


CALCULATED_COULMNS = [
    "days_until",
]

CLALIT_COLUMN_MAP = {
    "scraped_at": "timestamp",
    "doctor_name": "doctor_name",
    "profession": "profession",
    "next_available_date": "available_date",
    "clinic_address": "address",
}

CLALIT_USEFUL_COLUMNS = [
    "scraped_at",
    "group_name",
    "spec_name",
    "doctor_name",
    "profession",
    "next_available_date",
    "days_until",
    "clinic_name",
    "clinic_address",
    # "map_url",
    # "slots_link",
]


MACABI_COLUMN_MAP = {
    "group_name": "group_name",
}


def open_and_clean_df(csv_path: Path, columns_to_keep: list[str]) -> pd.DataFrame:
    raw_data = pd.read_csv(csv_path)
    data = raw_data[columns_to_keep]
    return data


def open_and_clean_clalit(csv_path: Path) -> pd.DataFrame:
    df = open_and_clean_df(csv_path, columns_to_keep=CLALIT_USEFUL_COLUMNS)
    df = df.rename(columns=CLALIT_COLUMN_MAP)
    existing_columns = [col for col in INTERESTING_COLUMNS if col in df.columns]
    df = df[existing_columns]
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["available_date"] = pd.to_datetime(df["available_date"], format="%d.%m.%Y")
    return df


def enrich_days_until(df: pd.DataFrame) -> pd.DataFrame:
    df["days_diff"] = (
        df["available_date"].dt.normalize() - df["timestamp"].dt.normalize()
    ).dt.days
    return df


def enrich_city(df: pd.DataFrame) -> pd.DataFrame:
    df["city"] = df["address"].str.split(", ").str[-1]
    return df


def open_and_clean_all(clalit_path: Path, macabi_path: Path) -> pd.DataFrame:
    clalit_df = open_and_clean_clalit(clalit_path)
    clalit_df = enrich_days_until(clalit_df)
    clalit_df = enrich_city(clalit_df)
    return pd.concat(
        [
            clalit_df,
        ],
        ignore_index=True,
    )
