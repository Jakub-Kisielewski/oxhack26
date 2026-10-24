import streamlit as st
import folium
from streamlit_folium import st_folium

st.title("Central London — TfL Zones 1 & 2")
st.caption(
    "Approximate area of interest. The boundary below is a placeholder — "
    "swap it for real TfL zone GeoJSON once we have the data."
)

CENTER = [51.509, -0.118]

# NOTE: folium uses [lat, lon] — the OPPOSITE order to pydeck's [lon, lat].
zone_boundary = [
    [51.540, -0.205],   # NW
    [51.540, -0.015],   # NE
    [51.465, -0.015],   # SE
    [51.465, -0.205],   # SW
]

stations = [
    {"name": "King's Cross St. Pancras", "lat": 51.5308, "lon": -0.1238},
    {"name": "Waterloo",                 "lat": 51.5031, "lon": -0.1132},
    {"name": "Liverpool Street",         "lat": 51.5178, "lon": -0.0823},
    {"name": "Victoria",                 "lat": 51.4952, "lon": -0.1441},
    {"name": "Paddington",               "lat": 51.5154, "lon": -0.1755},
]

m = folium.Map(location=CENTER, zoom_start=12, tiles="OpenStreetMap")

folium.Polygon(
    locations=zone_boundary,
    color="#1e78c8",
    weight=2,
    fill=True,
    fill_opacity=0.15,
    popup="Zones 1 & 2 (approx)",
).add_to(m)

for s in stations:
    folium.CircleMarker(
        location=[s["lat"], s["lon"]],
        radius=6,
        color="#c81e1e",
        fill=True,
        fill_opacity=0.9,
        popup=s["name"],
    ).add_to(m)

st_folium(m, width=None, height=600, returned_objects=[])

if st.button("← Back to Dashboard"):
    st.switch_page("src/ui/home.py")
