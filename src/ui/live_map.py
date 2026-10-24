"""Live camera map: every zones 1–2 JamCam by tier; click one for TfL's live still and clip."""
import time

import pydeck as pdk
import streamlit as st

from src.ui.live_data import load_cameras

TIER_LABELS = {2: "Route: clips every 15 s", 1: "Central box: stills every 60 s", 0: "Registered, not polled"}
TIER_COLOURS = {2: [220, 38, 38, 235], 1: [245, 158, 11, 225], 0: [59, 130, 246, 190]}
INACTIVE_COLOUR = [150, 150, 150, 140]
DECK_COLUMNS = ["camera_id", "name", "view", "lat", "lon", "tier", "active", "status", "color",
                "image_url", "video_url"]

st.title("Live cameras: zones 1 & 2")

cams = load_cameras()
if cams.empty:
    st.info("No cameras registered yet. Run `python -m src.pipeline.cameras`.")
    st.stop()

cams = cams.fillna({"view": "", "name": ""}).assign(
    color=[TIER_COLOURS[t] if a else INACTIVE_COLOUR for t, a in zip(cams["tier"], cams["active"])],
    status=["active" if a else "inactive" for a in cams["active"]],
)

map_col, panel_col = st.columns([2, 1])

with map_col:
    layer = pdk.Layer(
        "ScatterplotLayer",
        id="cameras",
        data=cams[DECK_COLUMNS],
        get_position=["lon", "lat"],
        get_fill_color="color",
        get_radius=25,
        radius_min_pixels=4,
        radius_max_pixels=12,
        stroked=True,
        get_line_color=[255, 255, 255],
        line_width_min_pixels=1,
        pickable=True,
        auto_highlight=True,
    )
    deck = pdk.Deck(
        layers=[layer],
        initial_view_state=pdk.ViewState(latitude=51.507, longitude=-0.118, zoom=12, pitch=0),
        map_style=pdk.map_styles.LIGHT,
        tooltip={"text": "{name}\nTier {tier} · {status}"},
    )
    event = st.pydeck_chart(deck, on_select="rerun", selection_mode="single-object", key="map", height=640)
    st.caption("🔴 tier 2 route · 🟠 tier 1 central box · 🔵 tier 0 not polled · ⚪ inactive")

selected = event.selection.objects.get("cameras", [])

with panel_col:
    if not selected:
        st.subheader("Camera viewer")
        st.write("Click a camera to see its live view.")
        summary = (cams.groupby("tier", as_index=False)
                   .agg(cameras=("camera_id", "size"), active=("active", "sum"))
                   .sort_values("tier", ascending=False))
        summary.insert(1, "meaning", summary["tier"].map(TIER_LABELS))
        st.dataframe(summary, hide_index=True)
    else:
        cam = selected[0]
        st.subheader(cam["name"])
        if cam["view"]:
            st.caption(cam["view"])
        st.markdown(f"**Tier {cam['tier']}**: {TIER_LABELS.get(cam['tier'], '')}  \n"
                    f"**Status:** {cam['status']}  \n`{cam['camera_id']}`")
        if not cam["active"]:
            st.warning("TfL lists this camera as unavailable; its feed may be blank.")
        bust = int(time.time())  # cache-buster so the browser fetches TfL's latest files
        st.image(f"{cam['image_url']}?t={bust}", caption="Latest still (TfL updates about every 5 min)",
                 width="stretch")
        st.video(f"{cam['video_url']}?t={bust}")
        st.caption("Loaded directly from TfL; nothing is stored or proxied.")
