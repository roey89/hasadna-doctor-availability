import folium
import geopandas
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
    # professions
    # --------------------------------------------------
 
    # exclude non-profession / bookkeeping columns from the dropdown
    excluded_cols = ["geometry", "city", "raw_points", "key_0"]
 
    default_column = "TotalAvailableSlots"
 
    # keep TotalAvailableSlots as the first, pre-selected dropdown entry so the
    # same choice-driven color scale mechanism also governs the default view,
    # instead of the default view living on a separate hardcoded color path
    profession_cols = [default_column] + [
        c for c in gdf.columns
        if c not in excluded_cols and c != default_column
    ]
 
    # --------------------------------------------------
    # GeoJson
    # --------------------------------------------------
 
    max_default = max(gdf[default_column].max(), 1)
 
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
            "fillColor": get_color(value, max_default),
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
    # dropdown
    # --------------------------------------------------
 
    # IMPORTANT: several Hebrew column names contain a literal `"` character
    # (e.g. ייעוץ רפואת להט"ב). If that character is dropped straight into
    # value="{c}" it breaks out of the HTML attribute and corrupts the
    # <select> markup, so selecting that (and sometimes subsequent) options
    # silently fails to pass the right column name to JS.
    # html.escape(..., quote=True) escapes " (and & < >) safely.
    options = "\n".join(
        '<option value="{val}"{sel}>{text}</option>'.format(
            val=html.escape(c, quote=True),
            text=html.escape(c),
            sel=" selected" if c == default_column else "",
        )
        for c in profession_cols
    )
 
    dropdown = f"""
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
    <b>Profession</b><br>
 
    <select id="professionSelect">
    {options}
    </select>
 
    </div>
    """
 
    m.get_root().html.add_child(folium.Element(dropdown))
 
    # --------------------------------------------------
    # javascript
    # --------------------------------------------------
 
    js = f"""
<script>
 
// Wrapped in "load" so this always runs AFTER folium's own script section
// has created the {grid.get_name()} layer variable. Without this, the code
// below throws a ReferenceError (the variable doesn't exist yet at the point
// this <script> tag is injected), which silently kills the whole block —
// including the addEventListener call — so the dropdown appears to do nothing.
window.addEventListener("load", function(){{
 
var geojson = {grid.get_name()};
 
function getColor(value, maxVal){{
 
    if(maxVal <= 0)
        maxVal = 1;
 
    var t = value / maxVal;
 
    t = Math.max(0, Math.min(1, t));
 
    var r, g;
 
    if(t <= 0.5){{
        // first half: green ramps 0 -> 255, red stays maxed out
        r = 255;
        g = Math.round(255 * (t / 0.5));
    }} else {{
        // second half: green stays maxed out, red ramps 255 -> 0
        r = Math.round(255 * (1 - (t - 0.5) / 0.5));
        g = 255;
    }}
 
    // 0 -> 144
    var b = Math.round(0 * (1 - t) + 144 * t);
 
    return "rgb(" + r + "," + g + "," + b + ")";
}}
 
document.getElementById("professionSelect").addEventListener("change",function(){{
 
    var column=this.value;
 
    var maxVal=0;
 
    geojson.eachLayer(function(layer){{
        var v=layer.feature.properties[column];
        v = (v===null || v===undefined) ? 0 : v;
 
        if(v>maxVal)
            maxVal=v;
    }});
 
    geojson.eachLayer(function(layer){{
 
        var value=layer.feature.properties[column];
        value = (value===null || value===undefined) ? 0 : value;
 
        layer.setStyle({{
            fillColor:getColor(value,maxVal),
            fillOpacity:0.75,
            color:"black",
            weight:0.4
        }});
 
        layer.unbindTooltip();
 
        layer.bindTooltip(
            "<b>City:</b> "
            + layer.feature.properties.city
            + "<br><b>"
            + column
            + ":</b> "
            + value
        );
 
    }});
 
}});
 
}});
 
</script>
"""
 
    m.get_root().html.add_child(folium.Element(js))
 
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
 
