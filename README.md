# coverage-map

Map source files to tests using coverage's per-test context tracking.

## Installation

```bash
uvx --from "git+https://github.com/benthomasson/coverage-map" coverage-map --help
```

## Usage

### Collect coverage data

```bash
coverage-map collect --source src --tests tests
```

This runs pytest with per-test coverage tracking and builds a mapping.

### Query which tests cover a file

```bash
coverage-map tests-for src/auth/client.py
```

### Query which files a test covers

```bash
coverage-map files-for tests/test_auth.py::test_login
```

### Show summary

```bash
coverage-map summary
coverage-map summary --max-tests 1  # Find under-tested files
```

## How it works

Uses coverage.py's "dynamic contexts" feature to track which test covered which lines. This gives precise mappings rather than relying on naming conventions.
