PY ?= .venv/bin/python
N ?= 3

.PHONY: init-db cameras poller workers status test app

init-db:
	$(PY) -m src.pipeline.db

cameras:
	$(PY) -m src.pipeline.cameras

poller:
	$(PY) -m src.pipeline.poller

workers:
	$(PY) -m src.pipeline.run_workers --n $(N)

status:
	$(PY) -m src.pipeline.status

test:
	$(PY) -m pytest -q

app:
	$(PY) -m streamlit run app.py
