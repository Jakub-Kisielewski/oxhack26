import pandas as pd
import streamlit as st

from src.ui import common, layers

common.page_header("Map explorer", "The base data behind the predictions: legal zones, protest targets, shops, "
                   "storage and past march routes.")

CATEGORIES = ["diplomatic", "government", "political_party", "townhall", "court", "memorial", "attraction"]
events = common.historical_events()
by_id = {e.event_id: e for e in events}

with st.sidebar:
    st.subheader("Layers")
    show_boundary = st.toggle("Zones 1-2 boundary", value=True, key="explore_boundary")
    show_legal = st.toggle("Legal zones", value=True, key="explore_legal")
    categories = st.multiselect("Protest targets", CATEGORIES, default=["diplomatic", "government"], key="explore_targets",
                                format_func=lambda c: c.replace("_", " ").title())
    cause = st.selectbox("Cause targets for", [None] + [c.key for c in common.causes()], key="explore_cause",
                         format_func=lambda k: "None" if k is None else next(c.label for c in common.causes() if c.key == k))
    show_shops = st.toggle("Shops", key="explore_shops")
    show_storage = st.toggle("Warehouses and storage", key="explore_storage")
    st.subheader("Past march")
    event_id = st.selectbox("Route", [None] + [e.event_id for e in events], key="explore_event",
                            format_func=lambda i: "None" if i is None else f"{by_id[i].date}: {by_id[i].name}")

deck_layers, legend, focus = [], [], []
if show_boundary:
    deck_layers.append(layers.boundary_layer())
if show_legal:
    deck_layers.append(layers.legal_zones_layer())
if show_shops:
    shops = common.get_db().cursor().execute("SELECT name, shop, lon, lat FROM shops WHERE lat IS NOT NULL").fetchall()
    deck_layers.append(layers.places_layer([{"name": n, "shop": s, "lonlat": (lon, lat)} for n, s, lon, lat in shops],
                                           "shops", layers.ink("muted", 170), 2, "Shop"))
    legend.append(("Shop", layers.ink_css("muted"), "dot"))
if show_storage:
    deck_layers.append(layers.places_layer(common.warehouses(), "storage", layers.rgba(layers.aqua_css(), 230), 5, "Storage"))
    legend.append(("Warehouse / storage", layers.aqua_css(), "dot"))
if categories:
    deck_layers.append(layers.targets_layer(common.targets(tuple(categories))))
    legend.append(("Protest target", layers.magenta_css(), "dot"))
if cause:
    cts = common.cause_targets(cause)
    deck_layers.append(layers.point_layer("cause_targets", [(t["lonlat"], f"{t['target_name']} (weight {t['weight']:.1f})")
                                                            for t in cts], radius=8))
    legend.append(("Cause target", layers.ink_css("primary"), "dot"))
    focus += [t["lonlat"] for t in cts]
event = by_id.get(event_id) if event_id else None
if event:
    deck_layers.append(layers.path_layer("event_route", event.path, event.name))
    deck_layers.append(layers.point_layer("event_waypoints", [(p, f"{i}. {name}") for i, (name, p) in
                                                              enumerate(event.waypoints, 1)], radius=6))
    legend += [("Past route", "#%02x%02x%02x" % tuple(layers.blue(0.8)[:3]), "line"),
               ("Published waypoint", layers.ink_css("primary"), "dot")]
    focus = list(event.path)

layers.show(layers.deck(deck_layers, layers.view_for(focus or [p for ring in common.boundary() for p in ring])),
            key="explore_deck", height=620)
if legend:
    layers.legend(legend)
if show_legal:
    layers.legal_legend()

if event:
    st.subheader(event.name)
    st.caption(f"{event.date}" + (f", start {event.start_time}" if event.start_time else "")
               + (f", organiser {event.organiser}" if event.organiser else "")
               + (f", about {event.turnout:,} people" if event.turnout else ""))
    st.dataframe(pd.DataFrame([{"#": i, "Waypoint": name} for i, (name, _) in enumerate(event.waypoints, 1)]),
                 hide_index=True, width="stretch")
