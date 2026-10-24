.PHONY: test audit compact run clean

PY ?= python3

test:
	$(PY) -m unittest discover -s tests -v

audit:
	$(PY) -m harnessopt audit .

compact:
	$(PY) -m harnessopt compact . --dry-run

run:
	$(PY) -m harnessopt --help

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete
