info: menu select

menu:
	echo "1 make start                - start dashboard (current dir as target)"
	echo "2 make start_at TARGET=path - start dashboard for a specific project"
	echo "3 make test                 - run all tests"
	echo "4 make test_smoke           - run smoke tests only"
	echo "5 make test_unit            - run unit tests only"
	echo "6 make test_integration     - run integration tests only"
	echo "7 make test_e2e             - run end-to-end tests"
	echo "8 make test_filter F=name   - run tests matching a name"
	echo "9 make setup                - create venv and install deps"
	echo "10 make update_phony        - update .PHONY in Makefile"

select:
	read -p ">>> " P ; make menu | grep "^$$P " | cut -d ' ' -f2-3 ; make menu | grep "^$$P " | cut -d ' ' -f2-3 | bash

.SILENT:

.PHONY: info menu select start start_at test test_smoke test_unit test_integration test_e2e test_filter setup update_phony

start:
	./run.sh

start_at:
	./run.sh $(TARGET)

test:
	./run-tests.sh

test_smoke:
	./run-tests.sh tests/smoke/ -v

test_unit:
	./run-tests.sh tests/unit/ -v

test_integration:
	./run-tests.sh tests/integration/ -v

test_e2e:
	./run-e2e-tests.sh

test_filter:
	./run-tests.sh -k "$(F)" -v

setup:
	python3 -m venv venv
	venv/bin/pip install -r requirements.txt

update_phony:
	echo "##### Updating .PHONY targets #####"
	targets=$$(grep -E '^[a-zA-Z_][a-zA-Z0-9_-]*:' Makefile | grep -v '=' | cut -d: -f1 | tr '\n' ' '); \
	sed -i.bak "s/^\.PHONY:.*/.PHONY: $$targets/" Makefile && \
	echo "Updated .PHONY: $$targets" && \
	rm -f Makefile.bak
