import folium
import geopandas
import json
import logging
import webbrowser
import jinja2
import html
from shapely.geometry import Point
from branca.element import MacroElement
import os


class ClickHandler(MacroElement):
    _template = jinja2.Template("""
    {% macro script(this, kwargs) %}

    function onGridClick(e){

        var layer = e.target;
        var props = layer.feature.properties;
        var points = JSON.parse(props.raw_points || "[]");

        var map = layer._map;

        var pointsLayer;

        map.eachLayer(function(l){
            if(l.options && l.options.name==="Clicked Points"){
                pointsLayer=l;
            }
        });

        if(pointsLayer){
            pointsLayer.clearLayers();
        }

        points.forEach(function(p){
            L.circleMarker([p[0],p[1]],{
                radius:5,
                color:"blue",
                fillColor:"#3388ff",
                fillOpacity:0.8
            }).addTo(pointsLayer);
        });

    }

    {{this._parent.get_name()}}.eachLayer(function(layer){
        layer.on("click",onGridClick);
    });

    {% endmacro %}
    """)

    def __init__(self):
        super().__init__()
        self._name = "ClickHandler"


def create_map(gdf, output_path):

    logging.info("Creating map...")

    # --------------------------------------------------
    # map center
    # --------------------------------------------------

    gdf_projected = gdf.to_crs(epsg=2039)

    center_x = gdf_projected.geometry.centroid.x.mean()
    center_y = gdf_projected.geometry.centroid.y.mean()

    centroid = geopandas.GeoSeries(
        [Point(center_x, center_y)],
        crs="EPSG:2039"
    ).to_crs(4326)

    center = [
        centroid.geometry.y.iloc[0],
        centroid.geometry.x.iloc[0]
    ]

    m = folium.Map(
        location=center,
        zoom_start=11,
        tiles="CartoDB positron"
    )

    # --------------------------------------------------
    # professions / kupahs
    # --------------------------------------------------

    # exclude non-profession / bookkeeping columns from the dropdown
    excluded_cols = ["geometry", "city", "raw_points", "key_0"]

    default_column = "TotalAvailableSlots"
    default_kupah = "All Kupahs"

    # Professions are just the remaining GeoDataFrame columns. Pulling them
    # from gdf.columns (schema-level) instead of inspecting row values is
    # what actually makes this reliable: every profession column exists
    # for every row regardless of what type its cell values end up as.
    profession_cols_set = {
        c for c in gdf.columns
        if c not in excluded_cols and c != default_column
    }

    def as_dict(value):
        """Nested profession->kupah data comes back from geopandas as an
        already-parsed Python dict in most cases (GDAL's GeoJSON driver
        preserves JSON-subtype fields and geopandas materializes them as
        dicts), but defensively also handle the case where it arrives as
        a raw JSON string."""

        if isinstance(value, dict):
            return value

        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return None
            return parsed if isinstance(parsed, dict) else None

        return None

    all_kupahs = set()

    for _, row in gdf.iterrows():
        for key in profession_cols_set:
            nested_data = as_dict(row.get(key))
            if nested_data:
                all_kupahs.update(nested_data.keys())

    profession_cols = [default_column] + sorted(profession_cols_set)
    kupah_cols = [default_kupah] + sorted(all_kupahs)

    # --------------------------------------------------
    # GeoJson
    # --------------------------------------------------

    # The initial max_default will be for "TotalAvailableSlots"
    max_default_val = max(gdf[default_column].max(), 1)

    def get_color(value, max_val):
        """Red -> yellow -> green gradient: green ramps up 0->255 over
        the first half of the range, then red ramps down 255->0 over the
        second half. Kept identical to the JS getColor() used for
        dropdown-driven updates so the initial render and every field
        switch use one consistent color scale."""

        max_val = max_val if max_val > 0 else 1
        t = max(0.0, min(1.0, value / max_val))

        if t <= 0.5:
            r = 255
            g = round(255 * (t / 0.5))
        else:
            r = round(255 * (1 - (t - 0.5) / 0.5))
            g = 255

        b = round(0 * (1 - t) + 144 * t)

        return f"rgb({r},{g},{b})"

    def style(feature):

        value = feature["properties"].get(default_column) or 0

        return {
            "fillColor": get_color(value, max_default_val),
            "fillOpacity": 0.75,
            "color": "black",
            "weight": 0.4,
        }

    tooltip = folium.GeoJsonTooltip(
        fields=["city", default_column],
        aliases=["City", "Available"]
    )

    grid = folium.GeoJson(
        gdf.to_json(),
        style_function=style,
        tooltip=tooltip,
    )

    grid.add_child(ClickHandler())
    grid.add_to(m)

    # --------------------------------------------------
    # clicked points layer
    # --------------------------------------------------

    folium.FeatureGroup(
        name="Clicked Points",
        show=True
    ).add_to(m)

    # --------------------------------------------------
    # dropdowns
    # --------------------------------------------------

    # Profession dropdown
    profession_options_html = "\n".join(
        '<option value="{val}"{sel}>{text}</option>'.format(
            val=html.escape(c, quote=True),
            text=html.escape(c),
            sel=" selected" if c == default_column else "",
        )
        for c in profession_cols
    )

    medical_field_dropdown = f"""
    <div style="
        position:fixed;
        top:10px;
        left:60px;
        z-index:9999;
        background:white;
        padding:10px;
        border:2px solid gray;
        border-radius:5px;
    ">
    <b>תחום השירות הרפואי</b><br>

    <select id="professionSelect">
    {profession_options_html}
    </select>

    </div>
    """
    m.get_root().html.add_child(folium.Element(medical_field_dropdown))

    # Kupah dropdown
    kupah_options_html = "\n".join(
        '<option value="{val}"{sel}>{text}</option>'.format(
            val=html.escape(c, quote=True),
            text=html.escape(c),
            sel=" selected" if c == default_kupah else "",
        )
        for c in kupah_cols
    )

    kupah_dropdown = f"""
    <div style="
        position:fixed;
        top:90px;
        left:60px;
        z-index:9999;
        background:white;
        padding:10px;
        border:2px solid gray;
        border-radius:5px;
    ">
    <b>קופת חולים</b><br>

    <select id="kupahSelect">
    {kupah_options_html}
    </select>

    </div>
    """
    m.get_root().html.add_child(folium.Element(kupah_dropdown))

    # --------------------------------------------------
    # javascript
    # --------------------------------------------------

    js_code = """
<script>

window.addEventListener("load", function(){

var geojson = %(geojson_name)s;
var professionSelect = document.getElementById("professionSelect");
var kupahSelect = document.getElementById("kupahSelect");

var currentProfession = professionSelect.value;
var currentKupah = kupahSelect.value;

function getColor(value, maxVal){
    if(maxVal <= 0) maxVal = 1;
    var t = value / maxVal;
    t = Math.max(0, Math.min(1, t));
    var r, g;
    if(t <= 0.5){
        r = 255;
        g = Math.round(255 * (t / 0.5));
    } else {
        r = Math.round(255 * (1 - (t - 0.5) / 0.5));
        g = 255;
    }
    var b = Math.round(0 * (1 - t) + 144 * t);
    return "rgb(" + r + "," + g + "," + b + ")";
}

function getValueForFeature(props, profession, kupah){
    if(profession === "%(default_column)s"){
        return props["%(default_column)s"] || 0;
    }

    // The nested profession data may already be a parsed JS object
    // (folium/geopandas embeds it directly as JSON in the map data) or,
    // less commonly, a raw JSON string -- handle both safely.
    var raw = props[profession];
    var professionData = raw;

    if(typeof raw === "string"){
        try {
            professionData = JSON.parse(raw || "{}");
        } catch(e){
            professionData = {};
        }
    }

    if(!professionData || typeof professionData !== "object"){
        professionData = {};
    }

    if(Object.keys(professionData).length > 0){
        if(kupah === "%(default_kupah)s"){
            var total = 0;
            for (var k in professionData) {
                if (professionData.hasOwnProperty(k)) {
                    total += (professionData[k] || 0);
                }
            }
            return total;
        } else {
            return professionData[kupah] || 0;
        }
    }

    return 0;
}

function calculateMaxVal(){
    var max = 0;
    geojson.eachLayer(function(layer){
        var val = getValueForFeature(layer.feature.properties, currentProfession, currentKupah);
        if(val > max) max = val;
    });
    return max;
}

function updateMap(){
    currentProfession = professionSelect.value;
    currentKupah = kupahSelect.value;

    var maxVal = calculateMaxVal();

    geojson.eachLayer(function(layer){
        var props = layer.feature.properties;
        var value = getValueForFeature(props, currentProfession, currentKupah);

        layer.setStyle({
            fillColor: getColor(value, maxVal),
            fillOpacity: 0.75,
            color: "black",
            weight: 0.4
        });

        layer.unbindTooltip();
        var tooltipContent = "<b>City:</b> " + props.city + "<br>";
        if (currentProfession === "%(default_column)s") {
            tooltipContent += "<b>Total Available Slots:</b> " + value;
        } else if (currentKupah === "%(default_kupah)s") {
            tooltipContent += "<b>" + currentProfession + " (All Kupahs):</b> " + value;
        } else {
            tooltipContent += "<b>" + currentProfession + " (" + currentKupah + "):</b> " + value;
        }
        layer.bindTooltip(tooltipContent);
    });
}

    professionSelect.addEventListener("change", updateMap);
    kupahSelect.addEventListener("change", updateMap);

    updateMap();
});

</script>
""" % {
        "geojson_name": grid.get_name(),
        "default_column": default_column,
        "default_kupah": default_kupah,
    }

    m.get_root().html.add_child(folium.Element(js_code))

    # --------------------------------------------------
    # save
    # --------------------------------------------------

    m.save(output_path)

    logging.info(f"Saved to {output_path}")

    webbrowser.open(
        "file://" + os.path.realpath(output_path)
    )


if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO)

    grid_file = "city_grid_data.geojson"
    map_file = "map.html"

    try:
        gdf = geopandas.read_file(grid_file, encoding="utf-8")

    except Exception as e:
        logging.error(e)
        raise

    if not gdf.empty:
        create_map(gdf, map_file)
    else:
        logging.warning("GeoJSON is empty.")