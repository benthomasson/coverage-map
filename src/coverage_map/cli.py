"""CLI for coverage-map."""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import click
import coverage


def _classname_to_node_id(classname: str, name: str) -> str:
    """Convert JUnit XML classname + test name to a pytest node ID.

    Pytest JUnit XML classnames are dot-separated. For module-level tests,
    the classname is the module path (e.g. "tests.test_auth"). For class-based
    tests, it includes the class (e.g. "tests.test_auth.TestAuth").

    We distinguish them by convention: Python class names start with an
    uppercase letter, while package/module names are lowercase/snake_case.

    Examples:
        >>> _classname_to_node_id("tests.test_auth", "test_login")
        'tests/test_auth.py::test_login'
        >>> _classname_to_node_id("tests.test_auth.TestAuth", "test_login")
        'tests/test_auth.py::TestAuth::test_login'
        >>> _classname_to_node_id("tests.unit.test_auth.TestAuth", "test_login")
        'tests/unit/test_auth.py::TestAuth::test_login'
    """
    if not classname:
        return name

    parts = classname.split(".")

    # Find the boundary between module path and class names.
    # Class names conventionally start with uppercase.
    module_parts: list[str] = []
    class_parts: list[str] = []
    for part in parts:
        if not class_parts and (not part or not part[0].isupper()):
            module_parts.append(part)
        else:
            class_parts.append(part)

    # Build the node ID: file_path::Class::test_name
    file_path = "/".join(module_parts) + ".py" if module_parts else classname + ".py"
    components = [file_path] + class_parts + [name]
    return "::".join(components)


def _context_to_node_id(context: str) -> str:
    """Convert a coverage.py context name to a pytest node ID.

    Coverage.py with ``dynamic_context = test_function`` records contexts as
    dotted Python paths (e.g. "tests.test_math.test_add"). This converts them
    to pytest node IDs (e.g. "tests/test_math.py::test_add") so they match
    the keys produced by JUnit XML parsing.

    Examples:
        >>> _context_to_node_id("tests.test_math.test_add")
        'tests/test_math.py::test_add'
        >>> _context_to_node_id("tests.test_auth.TestAuth.test_login")
        'tests/test_auth.py::TestAuth::test_login'
        >>> _context_to_node_id("tests/test_math.py::test_add")
        'tests/test_math.py::test_add'
    """
    # If it already looks like a node ID (contains ::), return as-is
    if "::" in context:
        return context

    # Split dotted path: everything before the last dot is the "classname",
    # the last component is the test function name
    if "." not in context:
        return context

    last_dot = context.rfind(".")
    classname = context[:last_dot]
    name = context[last_dot + 1:]
    return _classname_to_node_id(classname, name)


def parse_junit_xml(xml_path: str) -> dict[str, str]:
    """Parse a JUnit XML file and return a mapping of test node IDs to outcomes.

    Args:
        xml_path: Path to the JUnit XML file produced by pytest --junitxml.

    Returns:
        Dict mapping test node ID (e.g. "tests/test_auth.py::test_login") to
        outcome string: "passed", "failed", "error", or "skipped".
    """
    results: dict[str, str] = {}
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return results

    for testcase in tree.iter("testcase"):
        classname = testcase.get("classname", "")
        name = testcase.get("name", "")
        node_id = _classname_to_node_id(classname, name)

        # Determine outcome from child elements
        if testcase.find("failure") is not None:
            results[node_id] = "failed"
        elif testcase.find("error") is not None:
            results[node_id] = "error"
        elif testcase.find("skipped") is not None:
            results[node_id] = "skipped"
        else:
            results[node_id] = "passed"

    return results


def is_test_file(filename: str) -> bool:
    """Check if a filename is a test file or test infrastructure."""
    # Normalize path separators for cross-platform support
    normalized = filename.replace("\\", "/")
    basename = os.path.basename(normalized)

    # Check test infrastructure files
    if basename == "conftest.py":
        return True

    # Check common test patterns in basename
    # test_*.py, *_test.py, *_tests.py
    if basename.startswith("test_"):
        return True
    if basename.endswith("_test.py") or basename.endswith("_tests.py"):
        return True

    # Check if "tests" or "test" is a path segment (not just substring)
    # This avoids false positives like "attests/foo.py"
    parts = normalized.split("/")
    if "tests" in parts or "test" in parts:
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

    # Create a temp file for JUnit XML results
    junit_fd, junit_path = tempfile.mkstemp(suffix='.xml', prefix='coverage-map-junit-')
    os.close(junit_fd)

    try:
        # Build pytest command
        # Disable pytest-cov plugin and clear addopts to avoid conflicts
        cmd = [
            sys.executable, "-m", "coverage", "run",
            f"--rcfile={coveragerc_path}",
            "-m", "pytest",
            "-p", "no:pytest_cov",  # Disable pytest-cov (we use coverage directly)
            "-o", "addopts=",  # Clear addopts from pyproject.toml
            f"--junitxml={junit_path}",  # Capture test outcomes
            tests,
            "-v",
        ]

        if pytest_args:
            # Use shlex.split to handle quoted arguments properly
            try:
                cmd.extend(shlex.split(pytest_args))
            except ValueError as e:
                click.echo(f"Error: Invalid --pytest-args format: {e}", err=True)
                click.echo("Hint: Check for unmatched quotes in the argument string.", err=True)
                sys.exit(1)

        # Run pytest with coverage
        click.echo(f"\nRunning: {' '.join(cmd)}", err=True)
        result = subprocess.run(cmd)
    finally:
        # Clean up temp coveragerc
        os.unlink(coveragerc_path)

    # Parse test results from JUnit XML
    test_results = parse_junit_xml(junit_path)
    try:
        os.unlink(junit_path)
    except OSError:
        pass

    if result.returncode != 0:
        click.echo(click.style(f"Warning: pytest exited with code {result.returncode}", fg="yellow"), err=True)

    # Load coverage data
    click.echo("\nAnalyzing coverage data...", err=True)

    # Create coverage object to get the actual data file path
    # (respects COVERAGE_FILE env var and config)
    cov = coverage.Coverage()
    data_file = cov.config.data_file

    if not Path(data_file).exists():
        click.echo(f"Error: Coverage data file '{data_file}' not found.", err=True)
        click.echo("pytest may have failed to run. Check the output above for errors.", err=True)
        sys.exit(1)

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
                if not ctx:
                    continue
                # Clean up context name (remove "|run" suffix if present)
                test_name = ctx.split("|")[0] if "|" in ctx else ctx
                if not test_name:
                    continue
                # Convert dotted coverage context to node ID format
                # so keys match between file_to_tests and test_results
                test_name = _context_to_node_id(test_name)
                file_to_tests[rel_path].add(test_name)
                test_to_files[test_name].add(rel_path)

    # Convert sets to sorted lists for JSON
    # Count test result outcomes
    result_counts: dict[str, int] = defaultdict(int)
    for outcome in test_results.values():
        result_counts[outcome] += 1

    mapping = {
        "file_to_tests": {k: sorted(v) for k, v in sorted(file_to_tests.items())},
        "test_to_files": {k: sorted(v) for k, v in sorted(test_to_files.items())},
        "test_results": dict(sorted(test_results.items())),
        "stats": {
            "source_files": len(file_to_tests),
            "tests": len(test_to_files),
            "passed": result_counts.get("passed", 0),
            "failed": result_counts.get("failed", 0),
            "error": result_counts.get("error", 0),
            "skipped": result_counts.get("skipped", 0),
        }
    }

    # Save to file
    with open(output, "w") as f:
        json.dump(mapping, f, indent=2)

    click.echo(f"\nSaved mapping to {output}", err=True)
    click.echo(f"  {len(file_to_tests)} source files covered", err=True)
    click.echo(f"  {len(test_to_files)} tests tracked", err=True)
    if test_results:
        parts = []
        for status in ("passed", "failed", "error", "skipped"):
            count = result_counts.get(status, 0)
            if count:
                parts.append(f"{count} {status}")
        click.echo(f"  Results: {', '.join(parts)}", err=True)


def _find_tests_for_file(
    file_to_tests: dict[str, list[str]], source_file: str
) -> tuple[str | None, list[str]]:
    """Find tests covering a source file, with exact then partial matching.

    Returns:
        Tuple of (matched_file_path, list_of_tests).
    """
    # Try exact match first
    tests = file_to_tests.get(source_file, [])
    if tests:
        return source_file, tests

    # Try partial match
    partial_matches = []
    for file_path, file_tests in file_to_tests.items():
        if source_file in file_path or file_path.endswith(source_file):
            partial_matches.append((file_path, file_tests))

    if partial_matches:
        matched_file, tests = partial_matches[0]

        if len(partial_matches) > 1:
            click.echo(click.style(
                f"Warning: '{source_file}' matches {len(partial_matches)} files, showing first match.",
                fg="yellow"
            ), err=True)
            click.echo(click.style("Other matches:", fg="yellow"), err=True)
            for other_file, _ in partial_matches[1:]:
                click.echo(click.style(f"  {other_file}", fg="yellow"), err=True)
            click.echo("", err=True)

        return matched_file, tests

    return None, []


def _format_result_status(status: str) -> str:
    """Format a test result status with color."""
    colors = {
        "passed": "green",
        "failed": "red",
        "error": "red",
        "skipped": "yellow",
    }
    return click.style(status.upper(), fg=colors.get(status, "white"))


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
@click.option(
    "--results",
    is_flag=True,
    help="Include last-known test results (pass/fail/error/skip)",
)
@click.option(
    "--run",
    is_flag=True,
    help="Re-run the relevant tests and report results",
)
def tests_for(source_file, mapping, json_output, results, run):
    """
    Show which tests cover a given source file.

    Examples:

    \b
      coverage-map tests-for src/auth/client.py
      coverage-map tests-for src/auth/client.py --results
      coverage-map tests-for src/auth/client.py --run
      coverage-map tests-for src/auth/client.py --json-output | xargs pytest
    """
    try:
        with open(mapping) as f:
            data = json.load(f)
    except FileNotFoundError:
        click.echo(f"Error: Mapping file '{mapping}' not found. Run 'coverage-map collect' first.", err=True)
        sys.exit(1)

    file_to_tests = data.get("file_to_tests", {})
    test_results_data = data.get("test_results", {})

    matched_file, tests = _find_tests_for_file(file_to_tests, source_file)

    # --run: re-run the relevant tests with pytest
    if run:
        if not tests:
            click.echo(f"No tests found covering '{source_file}'")
            return
        click.echo(f"Running {len(tests)} test(s) covering {matched_file}...\n", err=True)
        cmd = [sys.executable, "-m", "pytest", "-v"] + list(tests)
        proc = subprocess.run(cmd)
        sys.exit(proc.returncode)

    if json_output:
        result_obj: dict = {"file": matched_file or source_file, "tests": tests}
        if results and test_results_data:
            result_obj["test_results"] = {
                t: test_results_data.get(t, "unknown") for t in tests
            }
        click.echo(json.dumps(result_obj, indent=2))
    else:
        if tests:
            if results and test_results_data:
                # Show results summary
                statuses: dict[str, int] = defaultdict(int)
                for test in tests:
                    status = test_results_data.get(test, "unknown")
                    statuses[status] += 1

                status_parts = []
                for s in ("passed", "failed", "error", "skipped", "unknown"):
                    if statuses.get(s):
                        status_parts.append(f"{statuses[s]} {s}")

                click.echo(f"{matched_file}: {len(tests)} tests ({', '.join(status_parts)})")

                # List each test with its status, failures first
                failed_tests = [t for t in tests if test_results_data.get(t) in ("failed", "error")]
                other_tests = [t for t in tests if test_results_data.get(t) not in ("failed", "error")]

                for test in failed_tests:
                    status = test_results_data.get(test, "unknown")
                    click.echo(f"  {_format_result_status(status)}: {test}")
                for test in other_tests:
                    status = test_results_data.get(test, "unknown")
                    click.echo(f"  {_format_result_status(status)}: {test}")
            else:
                click.echo(f"Tests covering {matched_file}:")
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

    stats = data.get("stats", {})

    click.echo(f"Coverage Mapping Summary")
    click.echo(f"========================")
    click.echo(f"Source files: {len(file_to_tests)}")
    click.echo(f"Tests: {len(test_to_files)}")

    # Show test result stats if available
    if any(stats.get(s) for s in ("passed", "failed", "error", "skipped")):
        parts = []
        for s in ("passed", "failed", "error", "skipped"):
            count = stats.get(s, 0)
            if count:
                parts.append(f"{count} {s}")
        click.echo(f"Results: {', '.join(parts)}")
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
