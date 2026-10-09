PYTHON ?= python3

.PHONY: test clean

test:
	$(PYTHON) -m unittest discover -s tests -t tests

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
