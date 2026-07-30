import folium
import geopandas
import logging
import webbrowser
import jinja2
from folium.features import JsCode
from shapely.geometry import Point
import branca.colormap as cm
from branca.element import MacroElement
import os


class ClickHandler(MacroElement):
    _template = jinja2.Template(u"""
        {% macro script(this, kwargs) %}
            function onGridClick_{{this._parent.get_name()}}(e) {
                var layer = e.target;
                var props = e.target.feature.properties;
                var points = props.raw_points;
                var map = e.target._map;

                var pointsLayer;
                map.eachLayer(function(l) {
                    if (l.options && l.options.name === 'Clicked Points') {
                        pointsLayer = l;
                    }
                });

                if (pointsLayer) {
                    pointsLayer.clearLayers();
                }

                if (points && points.length > 0) {
                    points.forEach(function(p) {
                        L.circleMarker([p[0], p[1]], {
                            radius: 5,
                            color: 'blue',
                            fillColor: '#3388ff',
                            fillOpacity: 0.8
                        }).addTo(pointsLayer);
                    });
                }
            }
            {{this._parent.get_name()}}.on('click', onGridClick_{{this._parent.get_name()}});
        {% endmacro %}
        """)
    def __init__(self):
        super(ClickHandler, self).__init__()
        self._name = 'ClickHandler'


def create_map(gdf, geo_json_path, map_output_path):
    """
    Creates a Folium map with a dropdown for selecting professions.
    """

    logging.info("Creating Folium map...")

    # -------------------------------------------------------
    # Calculate map center
    # -------------------------------------------------------
    gdf_projected = gdf.to_crs(epsg=2039)

    center_x = gdf_projected.geometry.centroid.x.mean()
    center_y = gdf_projected.geometry.centroid.y.mean()

    centroid = geopandas.GeoSeries(
        [Point(center_x, center_y)],
        crs="EPSG:2039"
    ).to_crs(epsg=4326)

    center_lat = centroid.geometry.y.iloc[0]
    center_lon = centroid.geometry.x.iloc[0]

    # -------------------------------------------------------
    # Create base map
    # -------------------------------------------------------
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=11,
        tiles="CartoDB positron"
    )

    # -------------------------------------------------------
    # Columns
    # -------------------------------------------------------
    profession_cols = [
        c for c in gdf.columns
        if c not in ["geometry", "key_0", "TotalAvailableSlots", "raw_points"]
    ]

    display_cols = ["TotalAvailableSlots"] + profession_cols

    # -------------------------------------------------------
    # Create one layer per profession
    # -------------------------------------------------------
    for column in display_cols:

        fg = folium.FeatureGroup(
            name=column,
            show=(column == "TotalAvailableSlots")   # initially visible
        )

        # Use a function generator to correctly capture the column variable
        def style_function_generator(col):
            def style_function(feature):
                # Ensure value is 0 if it's None (null in GeoJSON)
                value = feature["properties"].get(col) or 0
                max_value = gdf[col].max()
                colormap = cm.LinearColormap(
                    colors=["yellow", "orange", "red"],
                    vmin=0,
                    vmax=max_value if max_value > 0 else 1  # Avoid vmax=0
                )
                return {
                    "fillColor": colormap(value),
                    "color": "black",
                    "weight": 0.4,
                    "fillOpacity": 0.75,
                }
            return style_function

        tooltip = folium.GeoJsonTooltip(
            fields=["key_0", column],
            aliases=["Grid:", "Available Slots:"],
            sticky=False
        )
        
        grid_layer = folium.GeoJson(
            data=gdf.to_json(),
            style_function=style_function_generator(column),
            tooltip=tooltip,
        )
        
        grid_layer.add_child(ClickHandler())
        grid_layer.add_child(folium.features.GeoJsonPopup(fields=["key_0", column]))
        grid_layer.add_to(fg)


        fg.add_to(m)

    # -------------------------------------------------------
    # Layer selector (dropdown)
    # -------------------------------------------------------
    folium.LayerControl(collapsed=False).add_to(m)

    # -------------------------------------------------------
    # Add JS to show points on click
    # -------------------------------------------------------

    # Create a feature group to hold the clicked points
    points_fg = folium.FeatureGroup(name="Clicked Points", show=True).add_to(m)

    # -------------------------------------------------------
    # Save
    # -------------------------------------------------------
    m.save(map_output_path)
    logging.info(f"Map saved to '{map_output_path}'")

    try:
        webbrowser.open(f"file://{os.path.realpath(map_output_path)}")
    except Exception as e:
        logging.warning(f"Could not open browser: {e}")


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