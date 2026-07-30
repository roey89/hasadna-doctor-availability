
import pandas as pd
import geopandas
from shapely.geometry import Point, Polygon
import numpy as np
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_geodataframe(df):
    """
    Converts a pandas DataFrame to a GeoDataFrame.
    """
    logging.info("Creating GeoDataFrame from input DataFrame.")
    geometry = [Point(xy) for xy in zip(df['longitude'], df['latitude'])]
    return geopandas.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")

def create_grid(gdf, grid_size_km=1):
    """
    Creates a grid of a specified size in kilometers over the area of the GeoDataFrame.
    """
    logging.info(f"Creating {grid_size_km}x{grid_size_km} km grid.")
    # Define the bounding box of the data
    min_lon, min_lat, max_lon, max_lat = gdf.total_bounds
    
    # Approximate conversion from km to degrees
    lat_km_to_deg = grid_size_km / 111.32
    # 1 degree of longitude varies with latitude. Use the mean latitude of the data.
    mean_latitude = gdf.geometry.y.mean()
    lon_km_to_deg = grid_size_km / (111.32 * np.cos(np.radians(mean_latitude)))
    
    lat_step = lat_km_to_deg
    lon_step = lon_km_to_deg
    
    # Create the grid
    grid_cells = []
    # Add a small buffer to max_lat/lon to ensure the last cell is included
    for lat in np.arange(min_lat, max_lat + lat_step, lat_step):
        for lon in np.arange(min_lon, max_lon + lon_step, lon_step):
            grid_cells.append(Polygon([
                (lon, lat),
                (lon + lon_step, lat),
                (lon + lon_step, lat + lat_step),
                (lon, lat + lat_step)
            ]))
    logging.info(f"Generated {len(grid_cells)} grid cells.")        
    return geopandas.GeoDataFrame(grid_cells, columns=['geometry'], crs="EPSG:4326")

def aggregate_data_to_grid(gdf, grid):
    """
    Aggregates data from the GeoDataFrame onto the grid.
    """
    logging.info("Aggregating data to grid cells.")
    # Spatial join to assign points to grid cells
    joined_gdf = geopandas.sjoin(gdf, grid, how="inner", predicate='within')
    
    if joined_gdf.empty:
        logging.warning("No data points found within grid cells. Returning grid with empty data.")
        # Get unique professions from the original gdf to ensure all columns are present
        unique_professions = gdf['profession'].unique().tolist()
        
        # Create an empty DataFrame with grid index and all expected columns
        empty_data = pd.DataFrame(index=grid.index)
        for prof in unique_professions:
            empty_data[prof] = 0
        empty_data['TotalAvailableSlots'] = 0
        empty_data['RawLatLons'] = "No raw data available"
        
        grid_with_data = grid.join(empty_data)
        return grid_with_data

    # Aggregate available slots per profession per grid cell
    aggregated_slots = joined_gdf.groupby(['index_right', 'profession'])['AvailableSlots'].sum().unstack(fill_value=0)

    # Collect raw lat/lon data for each grid cell
    # Create a list of (lat, lon) tuples for each original point
    joined_gdf['raw_lat_lon'] = joined_gdf.apply(lambda row: (row.latitude, row.longitude), axis=1)

    # Group by grid cell index and aggregate these tuples into a list
    raw_lat_lons_per_cell = joined_gdf.groupby('index_right')['raw_lat_lon'].apply(list)

    # Combine aggregated slots and raw lat/lons
    aggregated_data = aggregated_slots.join(raw_lat_lons_per_cell.rename('raw_points'))

    # Add a total column for available slots, summing only the numeric profession columns
    profession_cols = [col for col in aggregated_data.columns if col not in ['raw_points']]
    aggregated_data['TotalAvailableSlots'] = aggregated_data[profession_cols].sum(axis=1)

    # Join back to the grid
    grid_with_data = grid.join(aggregated_data, on=grid.index.to_series().rename('index_right'))

    # Fill NaN values for cells that had no data points
    for col in profession_cols + ['TotalAvailableSlots']:
        grid_with_data[col].fillna(0, inplace=True)
    grid_with_data['raw_points'] = grid_with_data['raw_points'].apply(lambda d: d if isinstance(d, list) else [])
    logging.info("Data aggregation complete.")
    return grid_with_data

if __name__ == "__main__":
    DIARIES_FILE = "diaries.csv" # Not used here, but good to keep consistent
    PROCESSED_FILE = "processed_diaries.csv" 
    GRID_FILE = "grid_data.geojson"
    GRID_SIZE_KM = 5  # Grid size in kilometers
    
    try:
        df = pd.read_csv(PROCESSED_FILE)
    except FileNotFoundError:
        logging.error(f"Error: The file '{PROCESSED_FILE}' was not found. Please run process_data.py first.")
        exit()
    
    if not df.empty:
        gdf = create_geodataframe(df)
        
        # Check if gdf has valid geometry before proceeding
        if gdf.geometry.is_empty.all():
            logging.error("GeoDataFrame has no valid geometries. Skipping grid creation and aggregation.")
        else:
            grid = create_grid(gdf, grid_size_km=GRID_SIZE_KM)
            aggregated_grid = aggregate_data_to_grid(gdf, grid)
            
            # Save the aggregated data
            aggregated_grid.to_file(GRID_FILE, driver='GeoJSON')
            
            logging.info(f"Aggregated grid data saved to '{GRID_FILE}'")
            logging.info("Phase 2 complete.")
    else:
        logging.warning("Processed data file is empty. Skipping Phase 2.")
