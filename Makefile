# Wi-Fi QR colonial map. `make demo` renders with dummy credentials and validates.
PY      ?= .venv/bin/python
OUT     ?= build
# newest wifi-map-<W>x<H>.png
IMAGE   ?= $(shell ls -t $(OUT)/wifi-map-*x*.png 2>/dev/null | grep -v module-check | head -1)
ARGS    ?=
CONFIG  ?= config.yaml
export QRMAP_CONFIG := $(abspath $(CONFIG))

.PHONY: help venv fetch demo build validate test proof clean

help:
	@echo "make venv      create .venv and install pinned dependencies"
	@echo "make fetch     download OpenStreetMap data for config.yaml's location (cached in data/)"
	@echo "               any target takes CONFIG=other.yaml to map somewhere else; fetch and build take the same ARGS=\"--size ..\""
	@echo "make demo      render with dummy credentials, then validate"
	@echo "make build     render with real credentials (wifi.env / env vars / prompt), then validate"
	@echo "make validate  re-validate IMAGE=... (e.g. after editing in GIMP/Inkscape)"
	@echo "make proof     PDF of the whole sheet at 8 in on its long side for a cheap letter-size test print"
	@echo "make test      offline unit tests"

venv:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

fetch:
	$(PY) -m qrmap.osm $(ARGS)

demo:
	$(PY) -m qrmap.build --demo --out $(OUT) $(ARGS)

build:
	$(PY) -m qrmap.build --out $(OUT) $(ARGS)

validate:
	$(PY) -m qrmap.validate $(IMAGE)

proof: $(IMAGE)
	$(PY) -c "from PIL import Image; Image.MAX_IMAGE_PIXELS=None; im=Image.open('$(IMAGE)').convert('RGB'); im.thumbnail((3600, 3600), Image.LANCZOS); im.save('$(basename $(IMAGE))-proof-8in.pdf', resolution=450)"
	@echo "wrote $(basename $(IMAGE))-proof-8in.pdf (print at 100%, no 'fit to page')"

test:
	$(PY) -m pytest -q tests

clean:
	rm -rf $(OUT)
