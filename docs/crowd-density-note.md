# Crowd density (considered, out of scope)

We researched usable street width for march routing (OSM tags, lane counts, pavement allowances in
`edge_features.estimate_width`). A natural extension was **area_m2** and **capacity_people** at Fruin-style
densities (~2 people/m² is congested; ~4 to 5 people/m² is dangerous).

That supported an overspill model removed in scope; see [docs/design-decisions.md](design-decisions.md). The route classifier now uses **width_m** and
context only; capacity columns were dropped from the ingestion pipeline so every artefact column has a named
model consumer.
