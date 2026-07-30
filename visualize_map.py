import folium
import geopandas
import pandas as pd
import logging
import webbrowser
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_map(gdf, geo_json_path, map_output_path):
    """
    Creates and saves a Folium map with a choropleth layer.
    """
    logging.info("Creating Folium map...")

    # Calculate the center of the map
    center_lat = gdf.geometry.centroid.y.mean()
    center_lon = gdf.geometry.centroid.x.mean()

    # Initialize the map
    m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles="CartoDB positron")

    # Define columns for the tooltip, excluding geometry and index columns
    tooltip_cols = [col for col in gdf.columns if col not in ['geometry', 'key_0']]

    # Create the choropleth layer
    choropleth = folium.Choropleth(
        geo_data=gdf,
        name='Medical Service Availability',
        data=gdf,
        columns=['key_0', 'TotalAvailableSlots'],
        key_on='feature.properties.key_0',
        fill_color='YlOrRd',
        fill_opacity=0.7,
        line_opacity=0.2,
        legend_name='Total Available Slots per 1km² Grid',
        highlight=True
    ).add_to(m)

    # Add tooltips to the choropleth layer
    choropleth.geojson.add_child(
        folium.features.GeoJsonTooltip(fields=tooltip_cols, aliases=[col.replace('_', ' ').title() for col in tooltip_cols])
    )

    # Add layer control to toggle the choropleth
    folium.LayerControl().add_to(m)

    # Save the map to an HTML file
    m.save(map_output_path)
    logging.info(f"Map saved to '{map_output_path}'")

    # Open the map in a new browser tab
    try:
        webbrowser.open(f"file://{os.path.realpath(map_output_path)}")
        logging.info("Opening map in a new browser tab.")
    except Exception as e:
        logging.warning(f"Could not automatically open the map: {e}")

if __name__ == "__main__":
    GRID_FILE = "grid_data.geojson"
    MAP_FILE = "medical_service_map.html"

    try:
        # Load the GeoJSON data
        gdf = geopandas.read_file(GRID_FILE, encoding='utf-8')

    except Exception as e:
        logging.error(f"Error loading '{GRID_FILE}': {e}. Please ensure Phase 2 was completed successfully.")
        exit()

    if not gdf.empty:
        create_map(gdf, GRID_FILE, MAP_FILE)
        logging.info("Phase 3 complete.")
    else:
        logging.warning("GeoJSON data file is empty. Skipping map creation.")