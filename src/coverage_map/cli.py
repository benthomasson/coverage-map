"""CLI for coverage-map."""

import json
import os
import shlex
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import click
import coverage


def is_test_file(filename: str) -> bool:
    """Check if a filename is a test file."""
    # Check common test patterns
    basename = os.path.basename(filename)
    if basename.startswith("test_") or basename.endswith("_test.py"):
        return True
    # Check if in a tests directory
    if "/tests/" in filename or filename.startswith("tests/"):
        return True
    return False


@click.group()
@click.version_option()
def cli():
    """Map source files to tests using coverage context tracking."""
    pass


@cli.command()
@click.option(
    "--source",
    "-s",
    default="src",
    help="Source directory to measure coverage for (default: src)",
)
@click.option(
    "--tests",
    "-t",
    default="tests",
    help="Test directory (default: tests)",
)
@click.option(
    "--output",
    "-o",
    default="coverage-map.json",
    help="Output file for the mapping (default: coverage-map.json)",
)
@click.option(
    "--pytest-args",
    default="",
    help="Additional arguments to pass to pytest",
)
def collect(source, tests, output, pytest_args):
    """
    Run pytest with per-test coverage tracking and build the mapping.

    This runs all tests while tracking which tests cover which source files.
    Results are saved to a JSON file for later querying.
    """
    # Validate source directory exists
    if not Path(source).exists():
        click.echo(f"Error: Source directory '{source}' does not exist.", err=True)
        sys.exit(1)

    # Validate tests directory exists
    if not Path(tests).exists():
        click.echo(f"Error: Tests directory '{tests}' does not exist.", err=True)
        sys.exit(1)

    click.echo(f"Running pytest with coverage context tracking...", err=True)
    click.echo(f"  Source: {source}", err=True)
    click.echo(f"  Tests: {tests}", err=True)

    # Create temporary .coveragerc with dynamic context settings
    coveragerc_content = f"""[run]
source = {source}
dynamic_context = test_function

[report]
show_contexts = True
"""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.coveragerc', delete=False) as f:
        f.write(coveragerc_content)
        coveragerc_path = f.name

    try:
        # Build pytest command
        # Disable pytest-cov plugin and clear addopts to avoid conflicts
        cmd = [
            sys.executable, "-m", "coverage", "run",
            f"--rcfile={coveragerc_path}",
            "-m", "pytest",
            "-p", "no:pytest_cov",  # Disable pytest-cov (we use coverage directly)
            "-o", "addopts=",  # Clear addopts from pyproject.toml
            tests,
            "-v",
        ]

        if pytest_args:
            # Use shlex.split to handle quoted arguments properly
            cmd.extend(shlex.split(pytest_args))

        # Run pytest with coverage
        click.echo(f"\nRunning: {' '.join(cmd)}", err=True)
        result = subprocess.run(cmd)
    finally:
        # Clean up temp file
        os.unlink(coveragerc_path)

    if result.returncode != 0:
        click.echo(click.style(f"Warning: pytest exited with code {result.returncode}", fg="yellow"), err=True)

    # Load coverage data
    click.echo("\nAnalyzing coverage data...", err=True)

    coverage_file = Path(".coverage")
    if not coverage_file.exists():
        click.echo("Error: No .coverage file found. pytest may have failed to run.", err=True)
        click.echo("Check the pytest output above for errors.", err=True)
        sys.exit(1)

    cov = coverage.Coverage()
    try:
        cov.load()
    except coverage.CoverageException as e:
        click.echo(f"Error loading coverage data: {e}", err=True)
        sys.exit(1)

    data = cov.get_data()

    # Build mapping: source_file -> set of tests
    file_to_tests: dict[str, set[str]] = defaultdict(set)
    # Also build reverse: test -> set of source files
    test_to_files: dict[str, set[str]] = defaultdict(set)

    for filename in data.measured_files():
        # Skip test files themselves
        if is_test_file(filename):
            continue

        contexts = data.contexts_by_lineno(filename)
        if not contexts:
            continue

        # Get relative path
        try:
            rel_path = str(Path(filename).relative_to(Path.cwd()))
        except ValueError:
            rel_path = filename

        # Collect all tests that covered any line in this file
        for line_no, line_contexts in contexts.items():
            for ctx in line_contexts:
                # Context format is typically "test_file.py::test_function|run"
                # or just the test name depending on setup
                if ctx:
                    # Clean up context name (remove "|run" suffix if present)
                    test_name = ctx.split("|")[0] if "|" in ctx else ctx
                    if test_name:
                        file_to_tests[rel_path].add(test_name)
                        test_to_files[test_name].add(rel_path)

    # Convert sets to sorted lists for JSON
    mapping = {
        "file_to_tests": {k: sorted(v) for k, v in sorted(file_to_tests.items())},
        "test_to_files": {k: sorted(v) for k, v in sorted(test_to_files.items())},
        "stats": {
            "source_files": len(file_to_tests),
            "tests": len(test_to_files),
        }
    }

    # Save to file
    with open(output, "w") as f:
        json.dump(mapping, f, indent=2)

    click.echo(f"\nSaved mapping to {output}", err=True)
    click.echo(f"  {len(file_to_tests)} source files covered", err=True)
    click.echo(f"  {len(test_to_files)} tests tracked", err=True)


@cli.command()
@click.argument("source_file")
@click.option(
    "--mapping",
    "-m",
    default="coverage-map.json",
    help="Mapping file from 'collect' command (default: coverage-map.json)",
)
@click.option(
    "--json-output",
    is_flag=True,
    help="Output as JSON",
)
def tests_for(source_file, mapping, json_output):
    """
    Show which tests cover a given source file.

    Example: coverage-map tests-for src/auth/client.py
    """
    try:
        with open(mapping) as f:
            data = json.load(f)
    except FileNotFoundError:
        click.echo(f"Error: Mapping file '{mapping}' not found. Run 'coverage-map collect' first.", err=True)
        sys.exit(1)

    file_to_tests = data.get("file_to_tests", {})

    # Try exact match first
    tests = file_to_tests.get(source_file, [])

    # If not found, try partial match
    if not tests:
        for file_path, file_tests in file_to_tests.items():
            if source_file in file_path or file_path.endswith(source_file):
                tests = file_tests
                source_file = file_path
                break

    if json_output:
        click.echo(json.dumps({"file": source_file, "tests": tests}, indent=2))
    else:
        if tests:
            click.echo(f"Tests covering {source_file}:")
            for test in tests:
                click.echo(f"  {test}")
            click.echo(f"\nTotal: {len(tests)} test(s)")
        else:
            click.echo(f"No tests found covering {source_file}")


@cli.command()
@click.argument("test_name")
@click.option(
    "--mapping",
    "-m",
    default="coverage-map.json",
    help="Mapping file from 'collect' command (default: coverage-map.json)",
)
@click.option(
    "--json-output",
    is_flag=True,
    help="Output as JSON",
)
@click.option(
    "--all",
    "-a",
    "match_all",
    is_flag=True,
    help="Aggregate files from all matching tests (useful for package prefixes)",
)
def files_for(test_name, mapping, json_output, match_all):
    """
    Show which source files a test covers.

    Example: coverage-map files-for test_auth.py::test_login

    Use --all to aggregate files from all tests matching a prefix:
      coverage-map files-for tests.unit.core --all
    """
    try:
        with open(mapping) as f:
            data = json.load(f)
    except FileNotFoundError:
        click.echo(f"Error: Mapping file '{mapping}' not found. Run 'coverage-map collect' first.", err=True)
        sys.exit(1)

    test_to_files = data.get("test_to_files", {})

    if match_all:
        # Aggregate mode: find all tests matching the pattern
        all_files: set[str] = set()
        matched_tests: list[str] = []
        for test, test_files in test_to_files.items():
            if test_name in test:
                matched_tests.append(test)
                all_files.update(test_files)
        files = sorted(all_files)
    else:
        # Single match mode: try exact match first, then partial
        files = test_to_files.get(test_name, [])
        matched_tests = [test_name] if files else []

        if not files:
            # Try partial match, return first hit
            for test, test_files in test_to_files.items():
                if test_name in test:
                    files = test_files
                    test_name = test
                    matched_tests = [test]
                    break

    if json_output:
        result = {"pattern": test_name, "files": files}
        if match_all:
            result["matched_tests"] = len(matched_tests)
        click.echo(json.dumps(result, indent=2))
    else:
        if files:
            if match_all and len(matched_tests) > 1:
                click.echo(f"Files covered by {len(matched_tests)} tests matching '{test_name}':")
            else:
                click.echo(f"Files covered by {test_name}:")
            for f in files:
                click.echo(f"  {f}")
            click.echo(f"\nTotal: {len(files)} file(s)")
            if match_all and len(matched_tests) > 1:
                click.echo(f"({len(matched_tests)} tests matched)")
        else:
            click.echo(f"No files found for test {test_name}")


@cli.command()
@click.option(
    "--mapping",
    "-m",
    default="coverage-map.json",
    help="Mapping file from 'collect' command (default: coverage-map.json)",
)
@click.option(
    "--min-tests",
    default=0,
    help="Only show files with at least this many tests",
)
@click.option(
    "--max-tests",
    default=None,
    type=int,
    help="Only show files with at most this many tests (find under-tested files)",
)
def summary(mapping, min_tests, max_tests):
    """
    Show summary of coverage mapping.
    """
    try:
        with open(mapping) as f:
            data = json.load(f)
    except FileNotFoundError:
        click.echo(f"Error: Mapping file '{mapping}' not found. Run 'coverage-map collect' first.", err=True)
        sys.exit(1)

    file_to_tests = data.get("file_to_tests", {})
    test_to_files = data.get("test_to_files", {})

    click.echo(f"Coverage Mapping Summary")
    click.echo(f"========================")
    click.echo(f"Source files: {len(file_to_tests)}")
    click.echo(f"Tests: {len(test_to_files)}")
    click.echo()

    # Files by test count
    by_count = defaultdict(list)
    for f, tests in file_to_tests.items():
        count = len(tests)
        if count >= min_tests and (max_tests is None or count <= max_tests):
            by_count[count].append(f)

    if max_tests is not None and max_tests <= 2:
        click.echo(f"Under-tested files (≤{max_tests} tests):")
        for count in sorted(by_count.keys()):
            for f in sorted(by_count[count]):
                click.echo(f"  [{count}] {f}")
    else:
        click.echo("Files by test coverage:")
        for count in sorted(by_count.keys(), reverse=True)[:10]:
            click.echo(f"  {count} tests: {len(by_count[count])} files")


if __name__ == "__main__":
    cli()
