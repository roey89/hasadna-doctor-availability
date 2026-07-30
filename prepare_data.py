import pandas as pd
from pathlib import Path

USEFUL_COLUMNS = [
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

def open_and_clean_df(csv_path: Path, columns_to_keep: list[str] = USEFUL_COLUMNS) -> pd.DataFrame:
    raw_data = pd.read_csv(csv_path)
    data = raw_data[columns_to_keep]
    return data