import requests
import json
import time
import uuid

# --- Configuration ---
CITIES = {
    "5000": "תל אביב - יפו"
}

FIELDS = {
    "026": "אונקולוגיה"
}

SEARCH_API_URL = "https://serguide.maccabi4u.co.il/webapi/api/SearchPage/GetSearchPageSearch/"
CALENDAR_API_URL = "https://serguide.maccabi4u.co.il/webapi/api/Appointments/GetDoctorCalendarRIV"
OUTPUT_FILENAME = "maccabi_full_data_with_appointments.json"
REQUEST_DELAY_SECONDS = 1  # Delay between requests to be respectful to the server.

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
            "TreatPubTypeList": "768170005,768150013,768170003",
            "isKosher": 0
        }

        print(f"    - Fetching doctors page {page_number}/{total_pages}...")

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

    print(f"      - Fetching calendar for Dr. {doctor.get('LAST_NAME', '')} (ID: {doctor.get('EmployeeNumber')})...")

    try:
        response = session.post(CALENDAR_API_URL, json=payload, timeout=20)
        response.raise_for_status()
        calendar_data = response.json()
        time.sleep(REQUEST_DELAY_SECONDS)
        return calendar_data
    except requests.exceptions.RequestException as e:
        print(f"      - Error fetching calendar: {e}")
        return {"error": str(e)}

def main():
    """
    Main function to orchestrate the scraping process.
    """
    scraped_data = {}
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Content-Type': 'application/json',
        'Accept-Language': 'en-US,en;q=0.9,he;q=0.8',
        'Referer': 'https://serguide.maccabi4u.co.il/search-results-page/'
    }
    session = requests.Session()
    session.headers.update(headers)

    print("Starting final scraper...")

    for city_code, city_name in list(CITIES.items())[:1]: # Limit to first city
        print(f"Processing City: {city_name} ({city_code})")
        scraped_data[city_name] = {}

        for field_code, field_name in list(FIELDS.items())[:1]: # Limit to first field
            print(f"  -> Processing Field: {field_name} ({field_code})")
            
            doctors_list = get_doctors_for_criteria(session, city_code, field_code)
            
            print(f"  -> Found {len(doctors_list)} doctors. Now fetching their calendars...")
            
            for doctor in doctors_list[:1]: # Limit to first doctor
                # Add a new key to the doctor's dictionary to hold the calendar info
                doctor["appointments_calendar"] = get_doctor_calendar(session, doctor)

            # Store the results in the nested structure
            scraped_data[city_name][field_name] = {
                "doctors": doctors_list,
                "count": len(doctors_list)
            }
            print(f"  -> Finished processing calendars for {field_name} in {city_name}.")

    print(f"Scraping complete. Saving data to {OUTPUT_FILENAME}...")
    with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
        json.dump(scraped_data, f, ensure_ascii=False, indent=4)
        
    print("Done.")

if __name__ == "__main__":
    main()
