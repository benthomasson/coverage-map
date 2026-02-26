# Code Review Report

**Branch:** files:1
**Models:** claude, gemini
**Gate:** [BLOCK] BLOCK

## claude [CONCERN]

### src/coverage_map/cli.py (new file)
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** PARTIAL

New CLI implementation with several areas of concern detailed below.

### src/coverage_map/cli.py:collect
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** PARTIAL

- Line 65: `import tempfile` inside function is unconventional (minor)
- Lines 116-117: Test file detection (`"/tests/" in filename or filename.startswith("tests/")`) may miss test files in other patterns like `test_*.py` in the root or other directories
- Line 132: `if ctx and ctx != ""` is redundant - `ctx` alone handles empty string
- Line 76-83: `pytest_args.split()` on line 86 doesn't handle quoted arguments properly (e.g., `--pytest-args='-k "test foo"'` would break)
- No validation that `source` directory exists before running
- The coverage data loading (line 101-102) assumes `.coverage` file exists in cwd - could fail with confusing error if pytest didn't run properly

### src/coverage_map/cli.py:tests_for
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Simple lookup with partial match fallback. Lines 173-177 take first partial match which is reasonable behavior. Good error handling for missing mapping file.

### src/coverage_map/cli.py:files_for
**Verdict:** CONCERN
**Correctness:** QUESTIONABLE
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

- Lines 217-227: Logic flow is confusing. Line 219 resets `matched_tests = []` even when exact match exists, relying on partial match to re-find it. Works but hard to follow.
- The behavior differs subtly between exact match and partial match scenarios when `--all` is used. An exact match test would be included in aggregation via self-matching (`test_name in test_name`), but this is implicit rather than explicit.

### src/coverage_map/cli.py:summary
**Verdict:** PASS
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** WIRED

Straightforward summary display with filtering options. Logic is clear and correct.

### src/coverage_map/cli.py (entry point)
**Verdict:** CONCERN
**Correctness:** VALID
**Spec Compliance:** N/A
**Test Coverage:** UNTESTED
**Integration:** PARTIAL

Line 343 has `if __name__ == "__main__": cli()` for direct execution, but the diff doesn't show pyproject.toml or setup.py, so I cannot verify the `coverage-map` console script entry point is registered. Without this, users cannot run `coverage-map collect`.

### Self-Review
**Confidence:** MEDIUM
**Limitations:** - Test file not included in diff - cannot verify coverage claims
- pyproject.toml not included - cannot verify CLI entry point is properly registered
- Could not verify if there are existing callers or if this is truly a new feature
- Cannot see what other files exist in src/coverage_map/ to understand full module structure

### Feature Requests
- Include pyproject.toml/setup.py when CLI entry points are added/modified
- Include test files alongside implementation changes
- Show directory structure context for new files to understand placement

## gemini [BLOCK]

### ERROR
**Verdict:** BLOCK

Model invocation failed: Model gemini failed: (node:36356) [DEP0040] DeprecationWarning: The `punycode` module is deprecated. Please use a userland alternative instead.
(Use `node --trace-deprecation ...` to show where the warning was created)
When using Vertex AI, you must specify either:
• GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_LOCATION environment variables.
• GOOGLE_API_KEY environment variable (if using express mode).
Update your environment and try again (no reload needed if using .env)!

