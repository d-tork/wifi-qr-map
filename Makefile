# Wi-Fi QR colonial map. `make demo` renders with dummy credentials and validates.
PY      ?= .venv/bin/python
OUT     ?= build
IMAGE   ?= $(OUT)/wifi-map-12in.png
ARGS    ?=

.PHONY: help venv fetch demo build validate test proof clean

help:
	@echo "make venv      create .venv and install pinned dependencies"
	@echo "make fetch     download the OpenStreetMap extract (needs internet; cached in data/)"
	@echo "make demo      render with dummy credentials, then validate"
	@echo "make build     render with real credentials (wifi.env / env vars / prompt), then validate"
	@echo "make validate  re-validate IMAGE=... (e.g. after editing in GIMP/Inkscape)"
	@echo "make proof     8x8 in PDF of the artwork for a cheap letter-size test print"
	@echo "make test      offline unit tests"

venv:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

fetch:
	$(PY) -m qrmap.osm

demo:
	$(PY) -m qrmap.build --demo --out $(OUT) $(ARGS)

build:
	$(PY) -m qrmap.build --out $(OUT) $(ARGS)

validate:
	$(PY) -m qrmap.validate $(IMAGE)

proof: $(IMAGE)
	$(PY) -c "from PIL import Image; Image.MAX_IMAGE_PIXELS=None; Image.open('$(IMAGE)').convert('RGB').save('$(OUT)/proof-8in.pdf', resolution=450)"
	@echo "wrote $(OUT)/proof-8in.pdf (print at 100%, no 'fit to page')"

test:
	$(PY) -m pytest -q tests

clean:
	rm -rf $(OUT)
