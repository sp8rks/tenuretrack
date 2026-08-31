.PHONY: test lint run chaperone slides logo
test:
	python -m pytest -q
lint:
	python -m ruff check src tests tools
run:
	tenuretrack run --config $${CONFIG:-benchmark.yaml}
chaperone:
	tenuretrack chaperone --config $${CONFIG:-benchmark.yaml}
slides:
	tenuretrack slides --config $${CONFIG:-benchmark.yaml}
logo:
	python tools/prepare_logo.py
