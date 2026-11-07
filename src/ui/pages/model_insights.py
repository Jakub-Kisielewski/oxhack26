import streamlit as st

from src.config import BACKTEST_PATH
from src.models.backtest import read_backtest
from src.ui import charts

st.title("Leave-one-event-out backtest")
st.caption(
    "Metrics come from `data/models/backtest.json` after `python -m src.models.train`. "
    "Training data are published march plans joined by shortest paths, not GPS traces."
)

bt = read_backtest(BACKTEST_PATH)
if bt is None:
    st.warning("No backtest file yet. Run ingestion, then `python -m src.models.train`.")
    st.code("python ingest.py\npython -m src.models.train", language="bash")
else:
    st.markdown(f"**Events evaluated:** {bt.n_events} · **Saved at:** {bt.created_at}")
    charts.backtest_charts(bt)
    with st.expander("Per-event rows"):
        st.dataframe(
            [
                {
                    "event_id": r.event_id,
                    "model": r.model,
                    "mean_log_likelihood": r.mean_log_likelihood,
                    "top1_jaccard": r.top1_jaccard,
                    "destination_in_top3": r.destination_in_top3,
                }
                for r in bt.rows
            ],
            use_container_width=True,
        )

st.subheader("What the model can and can't claim")
st.markdown(
    """
- **Training data are planned routes.** Past marches are published itineraries joined by
  shortest paths.
- **Small sample.** Leave-one-event-out scores are honest but noisy with few labelled events.
- **No live prediction UI.** This app only visualises the saved backtest summary.
"""
)
