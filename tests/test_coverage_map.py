"""Tests for coverage-map: test results alongside coverage mapping."""

import json
import os
import tempfile
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from coverage_map.cli import (
    _classname_to_node_id,
    _context_to_node_id,
    _find_tests_for_file,
    _format_result_status,
    cli,
    is_test_file,
    parse_junit_xml,
)

SAMPLE_PROJECT_SRC = Path(__file__).parent / "sample_project"


@pytest.fixture(scope="session")
def sample_project(tmp_path_factory):
    """Copy sample project to a temp dir outside of 'tests/' to avoid is_test_file false positives."""
    import shutil
    dest = tmp_path_factory.mktemp("sample_proj")
    shutil.copytree(SAMPLE_PROJECT_SRC, dest, dirs_exist_ok=True)
    return dest


# ─── Unit tests: _classname_to_node_id ────────────────────────────────────

class TestClassnameToNodeId:
    def test_module_level_test(self):
        assert _classname_to_node_id("tests.test_auth", "test_login") == "tests/test_auth.py::test_login"

    def test_class_based_test(self):
        assert _classname_to_node_id("tests.test_auth.TestAuth", "test_login") == "tests/test_auth.py::TestAuth::test_login"

    def test_nested_package(self):
        assert _classname_to_node_id("tests.unit.test_auth.TestAuth", "test_login") == "tests/unit/test_auth.py::TestAuth::test_login"

    def test_empty_classname(self):
        assert _classname_to_node_id("", "test_login") == "test_login"

    def test_deeply_nested_module(self):
        assert _classname_to_node_id("tests.unit.sub.test_deep", "test_x") == "tests/unit/sub/test_deep.py::test_x"

    def test_multiple_class_levels(self):
        # e.g. nested classes
        result = _classname_to_node_id("tests.test_auth.TestAuth.TestInner", "test_login")
        assert result == "tests/test_auth.py::TestAuth::TestInner::test_login"

    def test_single_module(self):
        assert _classname_to_node_id("test_simple", "test_func") == "test_simple.py::test_func"


# ─── Unit tests: _context_to_node_id ──────────────────────────────────────

class TestContextToNodeId:
    def test_dotted_module_test(self):
        assert _context_to_node_id("tests.test_math.test_add") == "tests/test_math.py::test_add"

    def test_dotted_class_test(self):
        assert _context_to_node_id("tests.test_auth.TestAuth.test_login") == "tests/test_auth.py::TestAuth::test_login"

    def test_already_node_id(self):
        """Contexts already in node ID format should pass through unchanged."""
        assert _context_to_node_id("tests/test_math.py::test_add") == "tests/test_math.py::test_add"

    def test_no_dots(self):
        """Plain name with no dots should pass through unchanged."""
        assert _context_to_node_id("test_add") == "test_add"

    def test_nested_package(self):
        assert _context_to_node_id("tests.unit.sub.test_deep.test_x") == "tests/unit/sub/test_deep.py::test_x"


# ─── Unit tests: parse_junit_xml ──────────────────────────────────────────

class TestParseJunitXml:
    def _write_xml(self, content: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".xml")
        os.close(fd)
        Path(path).write_text(content)
        return path

    def test_passed_test(self):
        xml = self._write_xml(textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuite>
              <testcase classname="tests.test_auth" name="test_login" time="0.01"/>
            </testsuite>
        """))
        try:
            results = parse_junit_xml(xml)
            assert results == {"tests/test_auth.py::test_login": "passed"}
        finally:
            os.unlink(xml)

    def test_failed_test(self):
        xml = self._write_xml(textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuite>
              <testcase classname="tests.test_auth" name="test_login" time="0.01">
                <failure message="assert False">AssertionError</failure>
              </testcase>
            </testsuite>
        """))
        try:
            results = parse_junit_xml(xml)
            assert results == {"tests/test_auth.py::test_login": "failed"}
        finally:
            os.unlink(xml)

    def test_error_test(self):
        xml = self._write_xml(textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuite>
              <testcase classname="tests.test_auth" name="test_login" time="0.01">
                <error message="RuntimeError">traceback</error>
              </testcase>
            </testsuite>
        """))
        try:
            results = parse_junit_xml(xml)
            assert results == {"tests/test_auth.py::test_login": "error"}
        finally:
            os.unlink(xml)

    def test_skipped_test(self):
        xml = self._write_xml(textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuite>
              <testcase classname="tests.test_auth" name="test_login" time="0.00">
                <skipped message="reason"/>
              </testcase>
            </testsuite>
        """))
        try:
            results = parse_junit_xml(xml)
            assert results == {"tests/test_auth.py::test_login": "skipped"}
        finally:
            os.unlink(xml)

    def test_mixed_results(self):
        xml = self._write_xml(textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuite>
              <testcase classname="tests.test_auth" name="test_login" time="0.01"/>
              <testcase classname="tests.test_auth" name="test_logout" time="0.01">
                <failure message="fail">err</failure>
              </testcase>
              <testcase classname="tests.test_auth" name="test_skip" time="0.00">
                <skipped/>
              </testcase>
            </testsuite>
        """))
        try:
            results = parse_junit_xml(xml)
            assert results["tests/test_auth.py::test_login"] == "passed"
            assert results["tests/test_auth.py::test_logout"] == "failed"
            assert results["tests/test_auth.py::test_skip"] == "skipped"
        finally:
            os.unlink(xml)

    def test_invalid_xml(self):
        xml = self._write_xml("not valid xml <<<<")
        try:
            results = parse_junit_xml(xml)
            assert results == {}
        finally:
            os.unlink(xml)

    def test_class_based_in_xml(self):
        xml = self._write_xml(textwrap.dedent("""\
            <?xml version="1.0" encoding="utf-8"?>
            <testsuite>
              <testcase classname="tests.test_auth.TestAuth" name="test_login" time="0.01"/>
            </testsuite>
        """))
        try:
            results = parse_junit_xml(xml)
            assert "tests/test_auth.py::TestAuth::test_login" in results
        finally:
            os.unlink(xml)


# ─── Unit tests: is_test_file ─────────────────────────────────────────────

class TestIsTestFile:
    def test_test_prefix(self):
        assert is_test_file("test_auth.py") is True

    def test_test_suffix(self):
        assert is_test_file("auth_test.py") is True
        assert is_test_file("auth_tests.py") is True

    def test_conftest(self):
        assert is_test_file("conftest.py") is True
        assert is_test_file("tests/conftest.py") is True

    def test_in_tests_dir(self):
        assert is_test_file("tests/helpers.py") is True

    def test_in_test_dir(self):
        assert is_test_file("test/helpers.py") is True

    def test_source_file(self):
        assert is_test_file("src/auth/client.py") is False

    def test_attests_not_matched(self):
        """Ensure 'attests' directory is not falsely matched as test directory."""
        assert is_test_file("attests/foo.py") is False


# ─── Unit tests: _find_tests_for_file ─────────────────────────────────────

class TestFindTestsForFile:
    def test_exact_match(self):
        mapping = {"src/auth/client.py": ["test_a", "test_b"]}
        matched, tests = _find_tests_for_file(mapping, "src/auth/client.py")
        assert matched == "src/auth/client.py"
        assert tests == ["test_a", "test_b"]

    def test_partial_match(self):
        mapping = {"src/auth/client.py": ["test_a"]}
        matched, tests = _find_tests_for_file(mapping, "client.py")
        assert matched == "src/auth/client.py"
        assert tests == ["test_a"]

    def test_no_match(self):
        mapping = {"src/auth/client.py": ["test_a"]}
        matched, tests = _find_tests_for_file(mapping, "nonexistent.py")
        assert matched is None
        assert tests == []

    def test_endswith_match(self):
        mapping = {"src/auth/client.py": ["test_a"]}
        matched, tests = _find_tests_for_file(mapping, "auth/client.py")
        assert matched == "src/auth/client.py"


# ─── Unit tests: _format_result_status ────────────────────────────────────

class TestFormatResultStatus:
    def test_passed(self):
        result = _format_result_status("passed")
        assert "PASSED" in result

    def test_failed(self):
        result = _format_result_status("failed")
        assert "FAILED" in result

    def test_skipped(self):
        result = _format_result_status("skipped")
        assert "SKIPPED" in result

    def test_unknown_status(self):
        result = _format_result_status("unknown")
        assert "UNKNOWN" in result


# ─── CLI integration tests: tests-for ─────────────────────────────────────

class TestTestsForCommand:
    @pytest.fixture()
    def mapping_file(self, tmp_path):
        data = {
            "file_to_tests": {
                "src/auth/client.py": [
                    "tests/test_auth.py::test_login",
                    "tests/test_auth.py::test_logout",
                ],
                "src/utils/logger.py": [
                    "tests/test_utils.py::test_log",
                ],
            },
            "test_to_files": {
                "tests/test_auth.py::test_login": ["src/auth/client.py"],
                "tests/test_auth.py::test_logout": ["src/auth/client.py"],
                "tests/test_utils.py::test_log": ["src/utils/logger.py"],
            },
            "test_results": {
                "tests/test_auth.py::test_login": "passed",
                "tests/test_auth.py::test_logout": "failed",
                "tests/test_utils.py::test_log": "passed",
            },
            "stats": {
                "source_files": 2,
                "tests": 3,
                "passed": 2,
                "failed": 1,
                "error": 0,
                "skipped": 0,
            },
        }
        p = tmp_path / "coverage-map.json"
        p.write_text(json.dumps(data))
        return str(p)

    def test_basic_lookup(self, mapping_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["tests-for", "src/auth/client.py", "-m", mapping_file])
        assert result.exit_code == 0
        assert "test_login" in result.output
        assert "test_logout" in result.output

    def test_results_flag(self, mapping_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["tests-for", "src/auth/client.py", "-m", mapping_file, "--results"])
        assert result.exit_code == 0
        assert "2 tests" in result.output
        assert "1 passed" in result.output
        assert "1 failed" in result.output

    def test_results_failures_first(self, mapping_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["tests-for", "src/auth/client.py", "-m", mapping_file, "--results"])
        # The failed test should appear before the passed test
        failed_pos = result.output.find("test_logout")
        passed_pos = result.output.find("test_login")
        assert failed_pos < passed_pos, "Failed tests should be listed first"

    def test_json_output(self, mapping_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["tests-for", "src/auth/client.py", "-m", mapping_file, "--json-output"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["file"] == "src/auth/client.py"
        assert len(data["tests"]) == 2

    def test_json_output_with_results(self, mapping_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["tests-for", "src/auth/client.py", "-m", mapping_file, "--json-output", "--results"])
        data = json.loads(result.output)
        assert "test_results" in data
        assert data["test_results"]["tests/test_auth.py::test_login"] == "passed"
        assert data["test_results"]["tests/test_auth.py::test_logout"] == "failed"

    def test_partial_match(self, mapping_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["tests-for", "client.py", "-m", mapping_file])
        assert result.exit_code == 0
        assert "test_login" in result.output

    def test_no_match(self, mapping_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["tests-for", "nonexistent.py", "-m", mapping_file])
        assert result.exit_code == 0
        assert "No tests found" in result.output

    def test_missing_mapping_file(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["tests-for", "foo.py", "-m", "/nonexistent/path.json"])
        assert result.exit_code != 0
        assert "not found" in result.output


# ─── CLI integration tests: files-for ─────────────────────────────────────

class TestFilesForCommand:
    @pytest.fixture()
    def mapping_file(self, tmp_path):
        data = {
            "file_to_tests": {},
            "test_to_files": {
                "tests/test_auth.py::test_login": ["src/auth/client.py", "src/utils/logger.py"],
                "tests/test_auth.py::test_logout": ["src/auth/client.py"],
            },
            "test_results": {},
            "stats": {},
        }
        p = tmp_path / "coverage-map.json"
        p.write_text(json.dumps(data))
        return str(p)

    def test_exact_match(self, mapping_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["files-for", "tests/test_auth.py::test_login", "-m", mapping_file])
        assert result.exit_code == 0
        assert "src/auth/client.py" in result.output
        assert "src/utils/logger.py" in result.output

    def test_all_flag(self, mapping_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["files-for", "test_auth", "-m", mapping_file, "--all"])
        assert result.exit_code == 0
        assert "2 tests matched" in result.output


# ─── CLI integration tests: summary ───────────────────────────────────────

class TestSummaryCommand:
    @pytest.fixture()
    def mapping_file(self, tmp_path):
        data = {
            "file_to_tests": {
                "src/a.py": ["t1", "t2", "t3"],
                "src/b.py": ["t1"],
            },
            "test_to_files": {"t1": ["src/a.py", "src/b.py"], "t2": ["src/a.py"], "t3": ["src/a.py"]},
            "test_results": {"t1": "passed", "t2": "passed", "t3": "failed"},
            "stats": {"source_files": 2, "tests": 3, "passed": 2, "failed": 1, "error": 0, "skipped": 0},
        }
        p = tmp_path / "coverage-map.json"
        p.write_text(json.dumps(data))
        return str(p)

    def test_summary_output(self, mapping_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "-m", mapping_file])
        assert result.exit_code == 0
        assert "Source files: 2" in result.output
        assert "Tests: 3" in result.output
        assert "2 passed" in result.output
        assert "1 failed" in result.output

    def test_max_tests_filter(self, mapping_file):
        runner = CliRunner()
        result = runner.invoke(cli, ["summary", "-m", mapping_file, "--max-tests", "1"])
        assert result.exit_code == 0
        assert "Under-tested" in result.output
        assert "src/b.py" in result.output


# ─── End-to-end: collect on sample project ────────────────────────────────

@pytest.mark.slow
class TestCollectEndToEnd:
    """Run `coverage-map collect` on the sample project and verify output.

    The sample project is copied to a temp dir outside of tests/ to avoid
    is_test_file false positives on absolute paths.
    """

    def _run_collect(self, sample_project, output_file):
        """Run collect from within the sample project directory."""
        old_cwd = os.getcwd()
        try:
            os.chdir(sample_project)
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["collect", "-s", "src", "-t", "tests", "-o", output_file],
                catch_exceptions=False,
            )
            return result
        finally:
            os.chdir(old_cwd)

    def test_collect_produces_test_results(self, sample_project, tmp_path):
        """Full e2e: collect produces coverage-map.json with test_results and stats."""
        output_file = str(tmp_path / "coverage-map.json")
        result = self._run_collect(sample_project, output_file)
        assert Path(output_file).exists(), f"Output file not created. CLI output:\n{result.output}"

        with open(output_file) as f:
            data = json.load(f)

        # Verify structure
        assert "file_to_tests" in data
        assert "test_to_files" in data
        assert "test_results" in data
        assert "stats" in data

        # Verify test_results has entries
        test_results = data["test_results"]
        assert len(test_results) > 0, "test_results should not be empty"

        # Check that we have a mix of outcomes
        outcomes = set(test_results.values())
        assert "passed" in outcomes, "Should have at least one passed test"
        assert "failed" in outcomes, "Should have the intentionally failing test"

        # Check stats match
        stats = data["stats"]
        assert stats["passed"] > 0
        assert stats["failed"] > 0
        assert stats["passed"] + stats["failed"] + stats["error"] + stats["skipped"] == len(test_results)

        # Verify file_to_tests is populated
        assert len(data["file_to_tests"]) > 0, "file_to_tests should not be empty"

    def test_key_format_consistency(self, sample_project, tmp_path):
        """Verify that file_to_tests keys and test_results keys use the same format.

        Previously there was a bug where coverage contexts used dotted format
        and JUnit XML used node ID format. The _context_to_node_id fix normalizes
        coverage contexts to node ID format so keys match.
        """
        output_file = str(tmp_path / "coverage-map.json")
        self._run_collect(sample_project, output_file)

        with open(output_file) as f:
            data = json.load(f)

        # Get test names from file_to_tests
        coverage_test_names = set()
        for tests in data["file_to_tests"].values():
            coverage_test_names.update(tests)

        # Get test names from test_results
        junit_test_names = set(data["test_results"].keys())

        # Keys should overlap — both now use node ID format
        overlap = coverage_test_names & junit_test_names
        assert len(overlap) > 0, (
            "file_to_tests and test_results keys should overlap after _context_to_node_id fix"
        )

    def test_collect_then_tests_for_with_results(self, sample_project, tmp_path):
        """e2e: collect then tests-for --results shows actual pass/fail status."""
        output_file = str(tmp_path / "coverage-map.json")
        self._run_collect(sample_project, output_file)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["tests-for", "math_utils.py", "-m", output_file, "--results"],
        )
        assert result.exit_code == 0
        assert "tests" in result.output.lower()
        assert "passed" in result.output.lower()

    def test_collect_then_tests_for_json(self, sample_project, tmp_path):
        """e2e: collect then tests-for --json-output --results returns real statuses."""
        output_file = str(tmp_path / "coverage-map.json")
        self._run_collect(sample_project, output_file)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["tests-for", "string_utils.py", "-m", output_file, "--json-output", "--results"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "test_results" in data
        # string_utils tests include a failing test
        has_failed = any(v == "failed" for v in data["test_results"].values())
        assert has_failed, "string_utils should show the intentionally failing test"
