
import pandas as pd
from geopy.geocoders import Nominatim
import time
import json
import os
from prepare_data import open_and_clean_all

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
    Caches results to a file to avoid re-geocoding.
    """
    geolocator = Nominatim(user_agent="medical_service_visualizer")
    cache_file = 'cache/geocoded_locations.json'
    
    # Create cache directory if it doesn't exist
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)

    geocoded_locations = {}
    if os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            geocoded_locations = json.load(f)
        print(f"Loaded {len(geocoded_locations)} geocoded locations from cache.")

    # Create a new DataFrame with unique address/city pairs
    unique_locations = df[['address']].drop_duplicates().dropna()
    
    locations_to_geocode = unique_locations[~unique_locations['address'].isin(geocoded_locations.keys())]
    
    if not locations_to_geocode.empty:
        print(f"Geocoding {len(locations_to_geocode)} new unique address/city pairs...")
        for index, row in locations_to_geocode.iterrows():
            address = row['address']
            try:
                # Use the city from the data to improve accuracy
                full_address = f"{address}, Israel"
                location = geolocator.geocode(full_address)
                # Store with a tuple key
                if location:
                    geocoded_locations[address] = (location.latitude, location.longitude)
                else:
                    geocoded_locations[address] = (None, None)
                time.sleep(1)  # To respect Nominatim's usage policy
            except Exception as e:
                print(f"Error geocoding '{address}': {e}")
                geocoded_locations[address] = (None, None)
        
        # Save updated cache
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(geocoded_locations, f, ensure_ascii=False, indent=4)
        print("Geocoding complete. Cache updated.")
    else:
        print("All locations were found in the cache.")

    # Map the geocoded locations back to the original DataFrame
    def get_lat(row):
        location = geocoded_locations.get(row['address'])
        return location[0] if location else None

    def get_lon(row):
        location = geocoded_locations.get(row['address'])
        return location[1] if location else None

    df['latitude'] = df.apply(get_lat, axis=1)
    df['longitude'] = df.apply(get_lon, axis=1)
    
    return df

def clean_and_preprocess(df):
    """
    Cleans and preprocesses the data.
    """
    print("Cleaning and preprocessing data...")
    # Create AvailableSlots column
    df['AvailableSlots'] = df['available_date'].notna().astype(int)
    
    # Handle missing values
    df['address'].fillna('Unknown', inplace=True)
    df['profession'].fillna('Unknown', inplace=True)
    df['kupah'].fillna('Unknown', inplace=True)
    
    # Standardize profession names (example: stripping whitespace)
    df['profession'] = df['profession'].str.strip()
    df['kupah'] = df['kupah'].str.strip()
    
    # Clean city names: replace hyphens, strip spaces, and normalize internal spaces
    if 'city' in df.columns:
        df['city'] = df['city'].astype(str).str.replace('-', ' ', regex=False).str.strip().str.replace(r'\s+', ' ', regex=True)
        # Remove records where city is 'טל אל'
        df = df[df['city'] != 'טל אל']

    
    print("Data cleaning and preprocessing complete.")
    return df

if __name__ == "__main__":
    DIARIES_FILE = "diaries.csv"
    PROCESSED_FILE = "processed_diaries.csv"
    MERGED_FILE = r"data/clean/merged.csv"
    from prepare_data import open_and_clean_all
    
    # df = open_and_clean_all("diaries.csv", "")
    df = pd.read_csv(MERGED_FILE)

    
    if df is not None:
        df = clean_and_preprocess(df)
        print(df.columns)
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
