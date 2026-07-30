import requests
import json
import simplejson
import time
import uuid
import multiprocessing
import argparse

# --- Configuration ---
CITIES_PATH = "city_codes.json"
FIELDS_PATH = "field_codes.json"
CACHE_PATH = "cache.json"

SEARCH_API_URL = "https://serguide.maccabi4u.co.il/webapi/api/SearchPage/GetSearchPageSearch/"
CALENDAR_API_URL = "https://serguide.maccabi4u.co.il/webapi/api/Appointments/GetDoctorCalendarRIV"
OUTPUT_FILENAME = "maccabi_full_data_with_appointments.json"
REQUEST_DELAY_SECONDS = 1  # Delay between requests to be respectful to the server.

parser = argparse.ArgumentParser()
parser.add_argument("--num_cities", type=int, default=-1, help="How many cities to query")
parser.add_argument("--num_fields", type=int, default=-1, help="How many fields to query")
parser.add_argument("--processes", "-j", type=int, default = 8, help="Number of processes to query http with")

def get_doctors_for_criteria(session, city_code, field_code):
    """
    Fetches all doctors for a given city and field, handling pagination.
    """
    doctors = []
    page_number = 1
    total_pages = 1
    
    while page_number <= total_pages:
        payload = {
            "ChapterId": "001",
            "City": city_code,
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

            if data.get("Items"):
                doctors.extend(data["Items"])

            if page_number == 1:
                num_of_pages = data.get("NumOfPages", 1)
                if num_of_pages > 0:
                    total_pages = num_of_pages
            
            page_number += 1
            time.sleep(REQUEST_DELAY_SECONDS)

        except requests.exceptions.RequestException as e:
            print(f"    - Error fetching doctors page {page_number}: {e}")
            break
            
    return doctors

def get_doctor_calendar(session, doctor):
    """
    Fetches the appointment calendar for a single doctor.
    """
    if not doctor.get("EmployeeNumber") or not doctor.get("PositionId") or not doctor.get("PROFAREAS"):
        return {"error": "Missing required information for calendar lookup"}

    # We need to guess the correct 'cpt' code. Let's try the first one from PROFAREAS.
    cpt_code = doctor["PROFAREAS"][0] 
    
    payload = {
        "cpt": str(cpt_code),
        "drId": str(doctor["EmployeeNumber"]),
        "positionId": str(doctor["PositionId"]),
        "requestId": str(uuid.uuid4())
    }

    try:
        response = session.post(CALENDAR_API_URL, json=payload, timeout=20)
        response.raise_for_status()
        calendar_data = response.json()
        time.sleep(REQUEST_DELAY_SECONDS)
        return calendar_data
    except requests.exceptions.RequestException as e:
        print(f"      - Error fetching calendar: {e}. {payload=}")
        return {"error": str(e)}


def scrape_city(city_code, city_name, fields, field_codes, session_headers, num_fields):
    session = requests.Session()
    session.headers.update(session_headers)
    scraped_data = {}

    try:
        scraped_data[city_code] = {}
        fields_list = list(fields.items())
        fields_list = [tup for tup in fields_list if tup[0] in field_codes]
        if num_fields != -1:
            fields_list = fields_list[:num_fields]
        for j, (field_code, field_name) in enumerate(fields_list):
            print(f"  -> Processing Field: {field_name} ({field_code}) in city {city_name} ({city_code}) - {j+1} / {len(fields_list)}")
            doctors_list = get_doctors_for_criteria(session, city_code, field_code)
            
            # Store the results in the nested structure
            if len(doctors_list) > 0:
                scraped_data[city_code][field_code] = {
                    "doctors": doctors_list,
                    "count": len(doctors_list)
                }
    except Exception as e:
        print(f"Error occured while scraping for city {city_name} ({city_code}): {e}")
    return scraped_data



def main(num_cities, num_fields, processes):
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

    with open(CITIES_PATH, 'r') as f:
        CITIES = json.load(f)
    with open(FIELDS_PATH, 'r') as f:
        FIELDS = json.load(f)
    with open(CACHE_PATH, 'r') as f:
        CACHE = json.load(f)

    print("Starting final scraper...")

    scrape_args = [(city_code, city_name, FIELDS, CACHE[city_code], headers, num_fields) for city_code, city_name in CITIES.items()]
    if num_cities != -1:
        scrape_args = scrape_args[:num_cities]
    with multiprocessing.Pool(processes=processes) as pool:
        city_results = pool.starmap(scrape_city, scrape_args)
    for res in city_results:
        scraped_data.update(res)

    print(f"Scraping complete. Saving data to {OUTPUT_FILENAME}...")
    with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(scraped_data, f, ensure_ascii=False, indent=4)
        
    print("updating cache...")
    for scrape_arg in scrape_args:
        city_code = scrape_arg[0]
        num_fields = scrape_arg[5]
        CACHE[city_code] = list(scraped_data[city_code].keys()) + CACHE[city_code][num_fields:]
        with open(CACHE_PATH, 'w') as f:
            json.dump(CACHE, f)
    print("Done.")

if __name__ == "__main__":
    args = parser.parse_args()
    main(args.num_cities, args.num_fields, args.processes)
