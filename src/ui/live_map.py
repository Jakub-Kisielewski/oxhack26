"""Live camera map: zones 1–2 JamCams coloured by latest people count; click one for its live view and history."""
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

from src.ui.live_data import load_cameras, load_history, load_queue_stats, load_tier0_pause
from src.ui.live_display import DECK_COLUMNS, age_text, cache_buster, prepare, tier_label

st.title("Live cameras: zones 1 & 2")


@st.fragment(run_every=10)
def sidebar_stats() -> None:
    stats = load_queue_stats()
    st.subheader("Pipeline")
    if stats is None:
        st.caption("No pipeline DB yet.")
        return
    pause = load_tier0_pause()
    if pause:
        until = pd.Timestamp(pause["until"]).tz_convert("Europe/London").strftime("%H:%M")
        st.warning(f"tier 0 paused (bandwidth) until {until}")
    q = stats["by_status"]
    lag = stats["lag_seconds"]
    st.metric("Data lag (newest frame)", age_text(lag) if lag is not None else "n/a",
              help="Now minus the newest frame_time. TfL uploads every ~5 min, so this saw-tooths 0–5 min.")
    st.metric("Queue (pending / processing)", f"{q['pending']} / {q['processing']}")
    st.metric(f"Observations, last {stats['window_minutes']} min", stats["observations_recent"])
    spc = stats["mean_seconds_per_chunk"]
    st.metric("Mean processing per chunk", f"{spc * 1000:.0f} ms" if spc is not None else "n/a")
    if q["failed"]:
        st.caption(f"{q['failed']} failed chunks in total")


with st.sidebar:
    sidebar_stats()


@st.fragment(run_every=10)
def live_view() -> None:
    raw = load_cameras()
    if raw.empty:
        st.info("No cameras registered yet. Run `python -m src.pipeline.cameras`.")
        return
    now = datetime.now(timezone.utc)
    cams = prepare(raw, now)
    map_col, panel_col = st.columns([2, 1])

    with map_col:
        layer = pdk.Layer(
            "ScatterplotLayer", id="cameras", data=cams[DECK_COLUMNS],
            get_position=["lon", "lat"], get_fill_color="color", get_radius="radius",
            radius_min_pixels=4, radius_max_pixels=14, stroked=True, get_line_color=[60, 60, 60, 160],
            line_width_min_pixels=1, pickable=True, auto_highlight=True,
        )
        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=pdk.ViewState(latitude=51.507, longitude=-0.118, zoom=12, pitch=0),
            map_style=pdk.map_styles.LIGHT,
            tooltip={"text": "{name}\nTier {tier} · {status}\n{people_txt} · {age_txt}"},
        )
        event = st.pydeck_chart(deck, on_select="rerun", selection_mode="single-object", key="map", height=640)
        st.caption("Colour = latest people count (pale 0 → dark red 10+); grey = no current count, stale or "
                   "inactive. Bigger dots = higher tier (route cameras largest).")

    selected = event.selection.objects.get("cameras", [])
    with panel_col:
        if not selected:
            st.subheader("Camera viewer")
            st.write("Click a camera to see its live view.")
            busiest = cams[cams["fresh"]].nlargest(5, "people")[["name", "people", "tier", "age_s"]]
            st.markdown("**Busiest cameras now**")
            if busiest.empty:
                st.caption("No current counts yet.")
            else:
                st.dataframe(busiest.assign(age_s=(busiest["age_s"] / 60).round().astype(int)),
                             hide_index=True, column_config={"age_s": st.column_config.NumberColumn("age (min)")})
            return
        row = cams.set_index("camera_id").loc[selected[0]["camera_id"]]
        st.subheader(row["name"])
        if row["view"]:
            st.caption(row["view"])
        st.markdown(f"**Tier {row['tier']}**: {tier_label(row['tier'])}  \n"
                    f"**Status:** {row['status']}  \n`{selected[0]['camera_id']}`")
        if not row["active"]:
            st.warning("TfL lists this camera as unavailable; its feed may be blank.")
        if pd.notna(row["people"]):
            uncertainty = (f" ± {row['count_sd']:.1f}" if pd.notna(row.get("count_sd")) else "")
            raw = (f", raw detector count {row['raw_people']:g}" if pd.notna(row.get("raw_people")) else "")
            reading = (f"**Latest reading:** {round(row['people'], 1):g}{uncertainty} people, {row['age_txt']} "
                       f"({row['kind']}, quality {row['quality']}{raw})")
            extras = [f"density {row['density']:.2f}/m²" if pd.notna(row["density"]) else None,
                      f"speed {row['speed']:.2f} m/s" if pd.notna(row["speed"]) else None,
                      f"heading {row['heading']:.0f}°" if pd.notna(row["heading"]) else None]
            extras = [e for e in extras if e]
            st.markdown(reading + ("  \n" + ", ".join(extras) if extras else ""))
            if not row["fresh"]:
                st.caption("This reading is stale (older than 15 min).")
        else:
            st.markdown("**Latest reading:** none in the last hour"
                        + (" (this tier is not polled)" if "not polled" in tier_label(row["tier"]) else ""))
        bust = cache_buster(row)
        st.image(f"{row['image_url']}?t={bust}", caption="Latest still (TfL updates about every 5 min)",
                 width="stretch")
        st.video(f"{row['video_url']}?t={bust}")
        st.caption("Loaded directly from TfL; nothing is stored or proxied.")
        hist = load_history(selected[0]["camera_id"])
        st.markdown("**People, last 60 min**")
        if hist.empty or hist["people"].isna().all():
            st.caption("No readings in the last 60 min.")
        else:
            chart = (alt.Chart(hist.dropna(subset=["people"]))
                     .mark_line(point=True)
                     .encode(x=alt.X("frame_time:T", title=None), y=alt.Y("people:Q", title="people"),
                             tooltip=[alt.Tooltip("frame_time:T", format="%H:%M"), "people:Q", "quality:N"])
                     .properties(height=180))
            st.altair_chart(chart, width="stretch")


live_view()
