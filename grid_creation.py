import pandas as pd
import geopandas
import logging
import json
import os
import osmnx as ox

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
def aggregate_data_to_city_grid(df, city_grid):
    """Aggregates data from the GeoDataFrame onto the city grid."""
    logging.info("Aggregating data to city grid.")
    
    if df.empty:
        logging.warning("Input DataFrame is empty.")
        city_grid['TotalAvailableSlots'] = 0
        city_grid['raw_points'] = json.dumps([])
        return city_grid

    # --- New implementation starts here ---

    # 1. Create a dataframe to hold aggregated data, indexed by city.
    aggregated_df = pd.DataFrame(index=df['city'].unique())

    # 2. Calculate TotalAvailableSlots and raw_points.
    aggregated_df['TotalAvailableSlots'] = df.groupby('city')['AvailableSlots'].sum()
    aggregated_df['raw_points'] = json.dumps([]) # Kept for schema compatibility

    # 3. Aggregate profession data.
    if 'kupah' not in df.columns or df['kupah'].isnull().all():
        logging.warning("'kupah' column not found or is empty. Creating simple profession columns.")
        prof_data = df.groupby(['city', 'profession'])['AvailableSlots'].sum().unstack(fill_value=0)
    else:
        logging.info("Creating nested profession/kupah objects.")
        
        # Group by city, profession, and kupah.
        grouped = df.groupby(['city', 'profession', 'kupah'])['AvailableSlots'].sum().astype(int)
        
        # Pivot kupah to columns.
        pivoted = grouped.unstack(level='kupah', fill_value=0)
        
        # For each (city, profession), convert the row of kupah counts into a dictionary.
        # Only include kupahs with available slots.
        prof_as_dicts = pivoted.apply(lambda row: row[row > 0].to_dict(), axis=1)
        
        # Unstack professions to become columns, with dictionaries as values.
        prof_data = prof_as_dicts.unstack(level='profession')

    # 4. Join profession data into the main aggregated dataframe.
    if not prof_data.empty:
        aggregated_df = aggregated_df.join(prof_data)

    # 5. Merge with the geo-grid.
    grid_with_data = city_grid.merge(aggregated_df, left_on='city', right_index=True, how='left')

    # 6. Fill NaN/None values.
    grid_with_data['TotalAvailableSlots'] = grid_with_data['TotalAvailableSlots'].fillna(0).astype(int)
    grid_with_data['raw_points'].fillna(json.dumps([]), inplace=True)

    profession_cols = prof_data.columns if 'prof_data' in locals() and hasattr(prof_data, 'columns') else []
    for col in profession_cols:
        if col not in grid_with_data.columns:
            continue
            
        if 'kupah' in df.columns and not df['kupah'].isnull().all():
            # Fill missing profession data for a city with an empty dict.
            grid_with_data[col] = grid_with_data[col].apply(lambda x: {} if pd.isna(x) else x)
            grid_with_data[col] = grid_with_data[col].apply(json.dumps) # Serialize nested dict to JSON string
        else:
            grid_with_data[col].fillna(0, inplace=True)

    logging.info("Data aggregation complete.")
    return grid_with_data

if __name__ == "__main__":
    PROCESSED_FILE = "processed_diaries.csv"
    OUTPUT_FILE = "city_grid_data.geojson"

    print("This script now uses the 'osmnx' library to fetch city boundaries.")
    print("Please make sure it is installed (e.g., 'pip install osmnx').")

    try:
        df = pd.read_csv(PROCESSED_FILE)
    except FileNotFoundError:
        logging.error(f"Error: The file '{PROCESSED_FILE}' was not found.")
        exit()

    if df.empty:
        logging.warning("Processed data file is empty. Skipping.")
        exit()

    # Get unique city names from the data
    # Dropna to avoid issues with osmnx
    unique_cities = df['city'].dropna().unique()
    logging.info(f"Found {len(unique_cities)} unique cities: {unique_cities}")

    # Configure osmnx
    import osmnx.settings
    osmnx.settings.use_cache = True
    osmnx.settings.log_console = True
    osmnx.settings.user_agent = 'my-doctor-availability-app'
    
    # Caching for city polygons
    CITY_POLYGONS_CACHE = "city_polygons_cache.geojson"

    if os.path.exists(CITY_POLYGONS_CACHE):
        logging.info(f"Loading city polygons from cache: {CITY_POLYGONS_CACHE}")
        city_grid = geopandas.read_file(CITY_POLYGONS_CACHE)
    else:
        logging.info("Cache not found. Fetching city polygons from osmnx.")
        city_polygons = []
        for city_name in unique_cities:
            if not isinstance(city_name, str) or not city_name.strip():
                continue
            try:
                # Append ', Israel' to help osmnx find the city
                gdf_city = ox.geocode_to_gdf(f"{city_name}, Israel")
                gdf_city['city'] = city_name  # Add city name column for reference
                city_polygons.append(gdf_city)
            except Exception as e:
                logging.warning(f"Could not retrieve boundary for '{city_name}': {e}")
        
        if not city_polygons:
            logging.error("Could not retrieve any city boundaries. Aborting.")
            exit()

        # This is our new grid, combining all city polygons
        city_grid = pd.concat(city_polygons, ignore_index=True)
        # Keep only necessary columns for the grid
        city_grid = city_grid[['city', 'geometry']]
        
        # Save to cache
        city_grid.to_file(CITY_POLYGONS_CACHE, driver='GeoJSON')
        logging.info(f"Saved city polygons to cache: {CITY_POLYGONS_CACHE}")
    
    # Aggregate the point data onto the new city grid
    aggregated_grid = aggregate_data_to_city_grid(df, city_grid)

    aggregated_grid.to_file(OUTPUT_FILE, driver='GeoJSON')

    aggregated_grid.to_file(OUTPUT_FILE, driver='GeoJSON')
    
    logging.info(f"Aggregated city grid data saved to '{OUTPUT_FILE}'")
    logging.info("Phase 2 complete.")
