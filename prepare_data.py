import pandas as pd
from pathlib import Path
from datetime import datetime
import json

INTERESTING_COLUMNS = [
    "timestamp",
    "available_date",
    "kupah",
    "profession",
    "doctor_name",
    "city",
    "address",
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


MACCABI_USEFUL_COLUMNS = [
    "CITY_NAME",
    "prof_code",
    "CLOSEST_APPOINMENT_DATE",
    "PARTIALLY_ADRESS",
    "TITEL",
    "FIRST_NAME",
    "LAST_NAME",
]


MACCABI_COLUMN_MAP = {
    "CITY_NAME": "city",
    "CLOSEST_APPOINMENT_DATE": "available_date",
}


def open_maccabi_to_df(
    json_path: Path, columns_to_keep: list[str] = MACCABI_USEFUL_COLUMNS
) -> pd.DataFrame:
    with open(json_path, "r", encoding="utf-8") as file:
        maccabi_data = json.load(file)

    rows = []

    for prof_code, level_1 in maccabi_data.items():
        for city_code, level_2 in level_1.items():
            for doctor in level_2.get("doctors", []):
                rows.append(
                    {
                        "prof_code": city_code,
                        # "prof_code": prof_code, # TODO: swap when shanos updates the data
                        "city_code": city_code,
                        **doctor,
                    }
                )

    df = pd.json_normalize(rows)
    df = df[columns_to_keep]
    return df


def get_maccabi_field_codes(field_codes_path: str) -> dict:
    with open(field_codes_path, "r") as f:
        field_codes = json.load(f)
    return field_codes


def open_and_parse_maccabi(
    csv_path: Path,
    columns_to_keep=MACCABI_USEFUL_COLUMNS,
    field_codes_path="data/raw/maccabi/field_codes.json",
) -> pd.DataFrame:
    field_codes = get_maccabi_field_codes(field_codes_path)
    df = open_maccabi_to_df(csv_path, columns_to_keep=columns_to_keep)
    df["doctor_name"] = df["TITEL"] + " " + df["FIRST_NAME"] + " " + df["LAST_NAME"]
    df["address"] = df["PARTIALLY_ADRESS"] + ", " + df["CITY_NAME"]
    df["profession"] = df["prof_code"].map(field_codes).str[::-1]
    df["timestamp"] = datetime.now()
    df = df.rename(columns=MACCABI_COLUMN_MAP)
    df["kupah"] = "maccabi"
    existing_columns = [col for col in INTERESTING_COLUMNS if col in df.columns]
    df = df[existing_columns]
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["available_date"] = pd.to_datetime(df["available_date"])
    return df


def open_and_parse_clalit(
    csv_path: Path, columns_to_keep: list[str] = CLALIT_USEFUL_COLUMNS
) -> pd.DataFrame:
    raw_data = pd.read_csv(csv_path)
    df = raw_data[columns_to_keep]
    df = df.rename(columns=CLALIT_COLUMN_MAP)
    df["kupah"] = "clalit"
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


def open_and_clean_all(clalit_path: Path, maccabi_path: Path) -> pd.DataFrame:
    clalit_df = open_and_parse_clalit(clalit_path)
    maccabi_df = open_and_parse_maccabi(maccabi_path)
    clalit_df = enrich_days_until(clalit_df)
    clalit_df = enrich_city(clalit_df)
    maccabi_df = enrich_days_until(maccabi_df)
    return pd.concat(
        [
            clalit_df,
            maccabi_df,
        ],
        ignore_index=True,
    )
