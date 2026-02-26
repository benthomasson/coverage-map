# coverage-map

Map source files to tests using coverage.py's per-test context tracking. More accurate than naming conventions because it uses actual execution data.

## Installation

```bash
# Run directly with uvx (no install needed)
uvx --from "git+https://github.com/benthomasson/coverage-map" coverage-map --help

# Or install in a project
uv pip install "coverage-map @ git+https://github.com/benthomasson/coverage-map"
```

## Quick Start

```bash
# 1. Collect coverage data (runs pytest with per-test tracking)
coverage-map collect --source src --tests tests

# 2. Query which tests cover a file
coverage-map tests-for src/auth/client.py

# 3. Query which files a test covers
coverage-map files-for test_login
```

## Commands

### collect

Run pytest with per-test coverage tracking and build the mapping.

```bash
coverage-map collect --source src --tests tests -o coverage-map.json
```

Options:
- `--source, -s` — Source directory to measure (default: src)
- `--tests, -t` — Test directory to run (default: tests)
- `--output, -o` — Output file (default: coverage-map.json)
- `--pytest-args` — Additional pytest arguments

### tests-for

Find which tests cover a source file.

```bash
coverage-map tests-for src/auth/client.py
coverage-map tests-for client.py  # Partial match works

# JSON output
coverage-map tests-for src/auth/client.py --json-output
```

### files-for

Find which source files a test covers.

```bash
coverage-map files-for test_login
coverage-map files-for tests/test_auth.py::test_login

# Aggregate all tests matching a pattern
coverage-map files-for tests.unit.core --all
```

The `--all` flag aggregates files from all matching tests, useful for package prefixes:

```
$ coverage-map files-for tests.unit.core --all
Files covered by 136 tests matching 'tests.unit.core':
  src/myapp/auth/client.py
  src/myapp/utils/logger.py
  ...
Total: 37 file(s)
(136 tests matched)
```

### summary

Show coverage mapping statistics.

```bash
coverage-map summary
coverage-map summary --max-tests 1  # Find under-tested files
coverage-map summary --min-tests 5  # Find well-tested files
```

## Output Format

The `coverage-map.json` file contains:

```json
{
  "file_to_tests": {
    "src/auth/client.py": [
      "tests/test_auth.py::test_login",
      "tests/test_auth.py::test_logout"
    ]
  },
  "test_to_files": {
    "tests/test_auth.py::test_login": [
      "src/auth/client.py",
      "src/utils/logger.py"
    ]
  },
  "stats": {
    "source_files": 37,
    "tests": 136
  }
}
```

## Integration with multi-model-code-review

If you have [multi-model-code-review](https://github.com/benthomasson/multi-model-code-review) installed, it automatically uses `coverage-map.json` when reviewing code:

```bash
# Generate coverage map
coverage-map collect --source src --tests tests

# Run code review (auto-detects coverage-map.json)
code-review auto -b feature-branch
```

The review will show which tests cover each changed file:
```
Auto-lookup: 2 Python file(s) changed
  src/auth/client.py: 13 tests
  src/utils/logger.py: 91 tests
```

## How It Works

Uses coverage.py's `dynamic_context = test_function` feature to track which test covered which lines. This creates a temporary `.coveragerc` file:

```ini
[run]
source = src
dynamic_context = test_function

[report]
show_contexts = True
```

The tool also:
- Disables pytest-cov plugin (`-p no:pytest_cov`) to avoid conflicts
- Clears pyproject.toml addopts (`-o addopts=`) to avoid conflicting flags

## Requirements

- Python 3.11+
- pytest
- coverage.py 7.0+
