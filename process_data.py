
import pandas as pd
from geopy.geocoders import Nominatim
import time
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
    """
    geolocator = Nominatim(user_agent="medical_service_visualizer")
    
    # Create a new DataFrame with unique address/city pairs
    unique_locations = df[['address']].drop_duplicates().dropna()
    
    geocoded_locations = {}
    print(f"Geocoding {len(unique_locations)} unique address/city pairs...")

    for index, row in unique_locations.iterrows():
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

    # Map the geocoded locations back to the original DataFrame
    def get_lat(row):
        return geocoded_locations.get(row['address'])[0]

    def get_lon(row):
        return geocoded_locations.get(row['address'])[1]

    df['latitude'] = df.apply(get_lat, axis=1)
    df['longitude'] = df.apply(get_lon, axis=1)
    
    print("Geocoding complete.")
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
    
    # Standardize profession names (example: stripping whitespace)
    df['profession'] = df['profession'].str.strip()
    
    print("Data cleaning and preprocessing complete.")
    return df

if __name__ == "__main__":
    DIARIES_FILE = "diaries.csv"
    PROCESSED_FILE = "processed_diaries.csv"
    from prepare_data import open_and_clean_all
    
    df = open_and_clean_all("diaries.csv", "")

    
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
