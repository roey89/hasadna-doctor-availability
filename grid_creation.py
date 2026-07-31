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

    # Aggregate available slots per profession per city
    aggregated_slots = df.groupby(['city', 'profession'])['AvailableSlots'].sum().unstack(fill_value=0)

    # The data no longer contains lat/lon, so raw_points will be empty.
    # The column is kept for schema compatibility with the map visualization.
    raw_points_per_city = df.groupby('city').apply(lambda x: json.dumps([]))

    # Combine aggregated data
    aggregated_data = aggregated_slots.join(raw_points_per_city.rename('raw_points'))

    # Add a total column for available slots
    profession_cols = [col for col in aggregated_data.columns if col != 'raw_points']
    aggregated_data['TotalAvailableSlots'] = aggregated_data[profession_cols].sum(axis=1)
    # Join with city_grid on the city name
    grid_with_data = city_grid.merge(aggregated_data, on='city', how='left')

    # Fill NaN values for cities that had no data points
    all_agg_cols = profession_cols + ['TotalAvailableSlots']
    for col in all_agg_cols:
        grid_with_data[col] = grid_with_data[col].fillna(0)
    grid_with_data['raw_points'] = grid_with_data['raw_points'].fillna(json.dumps([]))
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
