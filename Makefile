.PHONY: test lint run chaperone slides
test:
	pytest -q
lint:
	ruff check src tests
run:
	tenuretrack run --config $${CONFIG:-benchmark.yaml}
chaperone:
	tenuretrack chaperone --config $${CONFIG:-benchmark.yaml}
slides:
	tenuretrack slides --config $${CONFIG:-benchmark.yaml}
