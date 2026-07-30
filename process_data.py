
import pandas as pd
from geopy.geocoders import Nominatim
import time

def load_data(file_path):
    """
    Loads data from a CSV file.
    """
    try:
        df = pd.read_csv(file_path)
        print("Successfully loaded the data.")
        return df
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
        return None

def geocode_addresses(df):
    """
    Geocodes addresses and adds latitude and longitude columns.
    """
    geolocator = Nominatim(user_agent="medical_service_visualizer")
    
    # Get unique addresses to avoid redundant geocoding
    unique_addresses = df['clinic_address'].dropna().unique()
    
    geocoded_locations = {}
    print(f"Geocoding {len(unique_addresses)} unique addresses...")

    for address in unique_addresses:
        try:
            # Add 'Tel Aviv' to the address to improve accuracy
            full_address = f"{address}, Tel Aviv, Israel"
            location = geolocator.geocode(full_address)
            if location:
                geocoded_locations[address] = (location.latitude, location.longitude)
            else:
                geocoded_locations[address] = (None, None)
            time.sleep(1)  # To respect Nominatim's usage policy
        except Exception as e:
            print(f"Error geocoding '{address}': {e}")
            geocoded_locations[address] = (None, None)
            
    df['latitude'] = df['clinic_address'].map(lambda addr: geocoded_locations.get(addr, (None, None))[0])
    df['longitude'] = df['clinic_address'].map(lambda addr: geocoded_locations.get(addr, (None, None))[1])
    
    print("Geocoding complete.")
    return df

def clean_and_preprocess(df):
    """
    Cleans and preprocesses the data.
    """
    print("Cleaning and preprocessing data...")
    # Create AvailableSlots column
    df['AvailableSlots'] = df['next_available_date'].notna().astype(int)
    
    # Handle missing values
    df['clinic_address'].fillna('Unknown', inplace=True)
    df['profession'].fillna('Unknown', inplace=True)
    
    # Standardize profession names (example: stripping whitespace)
    df['profession'] = df['profession'].str.strip()
    
    print("Data cleaning and preprocessing complete.")
    return df

if __name__ == "__main__":
    DIARIES_FILE = "diaries.csv"
    PROCESSED_FILE = "processed_diaries.csv"
    
    df = load_data(DIARIES_FILE)
    
    if df is not None:
        df = clean_and_preprocess(df)
        print(df.columns)
        df = df[['search_city', 'clinic_address', 'profession', 'next_available_date', 'AvailableSlots']]
        print(df.head())

        df = geocode_addresses(df)
        print(df.head())
        
        # Drop rows where geocoding failed
        df.dropna(subset=['latitude', 'longitude'], inplace=True)
        
        df.to_csv(PROCESSED_FILE, index=False)
        print(f"Processed data saved to '{PROCESSED_FILE}'")
        print("\nProcessed Data Info:")
        df.info()
        print("\nRows with failed geocoding dropped.")
        print("Phase 1 complete.")
