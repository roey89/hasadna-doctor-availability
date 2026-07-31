import requests
import json
import time
import uuid
import argparse
import multiprocessing
from tqdm import tqdm

# --- Configuration ---
FIELDS_PATH = "data/clean/maccabi/field_codes.json"

SEARCH_API_URL = "https://serguide.maccabi4u.co.il/webapi/api/SearchPage/GetSearchPageSearch/"
CALENDAR_API_URL = "https://serguide.maccabi4u.co.il/webapi/api/Appointments/GetDoctorCalendarRIV"
OUTPUT_FILENAME = "data/raw/maccabi/maccabi_full_data_with_appointments.json"
REQUEST_DELAY_SECONDS = 1  # Delay between requests to be respectful to the server.

parser = argparse.ArgumentParser()
parser.add_argument("--num_fields", "-n", type=int, default=-1, help="How many fields to query")


def query_by_field(field_code, page_number, session_headers):
    session = requests.Session()
    session.headers.update(session_headers)
    payload = {
        "ChapterId": "001",
        "Field": field_code,
        "InitiatorCode": "001",
        "IsMobileApplication": 0,
        "ModuleName": "doctorssearchresults",
        "PageNumber": str(page_number),
        "RequestId": str(uuid.uuid4()),
        "Source": "SearchPage",
        "isKosher": 0
    }

    try: 
        response = session.post(SEARCH_API_URL, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        print(f"    - Error fetching doctors page 1: {e}")
        return {}


def get_doctors_for_field(session_headers, field_code):
    """
    Fetches all doctors for a given field, handling pagination.
    """
    doctors = []
    total_pages = 1

    data = query_by_field(field_code, page_number=1, session_headers=session_headers)
    if data == {}: # Fetch error
        return doctors
    num_of_pages = data.get("NumOfPages", 1)
    if num_of_pages > 0:
        total_pages = num_of_pages
    tqdm.write(f"fetching {total_pages} pages of field {field_code}...")
    with multiprocessing.Pool(min(total_pages, 32)) as pool:
        datas = pool.starmap(query_by_field, [(field_code, i, session_headers) for i in range(total_pages)])
        for data in datas:
            if data.get("Items"):
                doctors.extend(data["Items"])
    return doctors


def scrape_field(field_code, session_headers):
    scraped_data = {}
    doctors_list = get_doctors_for_field(session_headers, field_code)
    for doctor_data in doctors_list:
        city_code = doctor_data['CITY_CODE']
        if city_code not in scraped_data:
            scraped_data[city_code] = []
        scraped_data[city_code].append(doctor_data)
    return scraped_data




def main(num_fields):
    """
    Main function to orchestrate the scraping process.
    """
    scraped_data = {}
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Content-Type': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9,he;q=0.8',
        'Referer': 'https://serguide.maccabi4u.co.il/heb/doctors/doctorssearchresults/?'
    }

    with open(FIELDS_PATH, 'r') as f:
        FIELDS = json.load(f)

    print("Starting scraping...")
    scraped_data = {}
    field_keys = list(FIELDS.keys())
    if num_fields != -1:
        field_keys = field_keys[:num_fields]
    for field_code in tqdm(field_keys):
        scraped_data[field_code] = scrape_field(field_code, headers)


    print(f"Scraping complete. Saving data to {OUTPUT_FILENAME}...")
    with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(scraped_data, f, ensure_ascii=False, indent=4)
    print("Done.")

if __name__ == "__main__":
    args = parser.parse_args()
    main(args.num_fields)
