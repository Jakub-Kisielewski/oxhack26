# Crowd density (considered, out of scope)

We researched usable street width for march routing (OSM tags, lane counts, pavement allowances in
`edge_features.estimate_width`). A natural extension was **area_m2** and **capacity_people** at Fruin-style
densities (~2 people/m² congested; ~4–5 m² dangerous).

That supported an overspill model removed in `CLEANUP.md`. The route classifier now uses **width_m** and
context only; capacity columns were dropped from the ingestion pipeline so every artefact column has a named
model consumer.
