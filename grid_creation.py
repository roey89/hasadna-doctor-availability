
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

def create_grid(gdf):
    """
    Creates a 1x1 km grid over the area of the GeoDataFrame.
    """
    logging.info("Creating 1x1 km grid.")
    # Define the bounding box of the data
    min_lon, min_lat, max_lon, max_lat = gdf.total_bounds
    
    # Approximate conversion from km to degrees
    lat_km_to_deg = 1 / 111.32
    # 1 degree of longitude varies with latitude. Use the mean latitude of the data.
    mean_latitude = gdf.geometry.y.mean()
    lon_km_to_deg = 1 / (111.32 * np.cos(np.radians(mean_latitude)))
    
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
    
    # Aggregate data
    aggregated_grid = joined_gdf.groupby(['index_right', 'profession'])['AvailableSlots'].sum().unstack(fill_value=0)
    
    # Add a total column
    aggregated_grid['TotalAvailableSlots'] = aggregated_grid.sum(axis=1)

    # Join back to the grid
    grid_with_data = grid.join(aggregated_grid, on=grid.index.to_series().rename('index_right'))
    grid_with_data.fillna(0, inplace=True)
    logging.info("Data aggregation complete.")
    return grid_with_data

if __name__ == "__main__":
    DIARIES_FILE = "diaries.csv" # Not used here, but good to keep consistent
    PROCESSED_FILE = "processed_diaries.csv" 
    GRID_FILE = "grid_data.geojson"
    
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
            grid = create_grid(gdf)
            aggregated_grid = aggregate_data_to_grid(gdf, grid)
            
            # Save the aggregated data
            aggregated_grid.to_file(GRID_FILE, driver='GeoJSON')
            
            logging.info(f"Aggregated grid data saved to '{GRID_FILE}'")
            logging.info("Phase 2 complete.")
    else:
        logging.warning("Processed data file is empty. Skipping Phase 2.")
