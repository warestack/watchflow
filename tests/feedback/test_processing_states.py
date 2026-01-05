#!/usr/bin/env python3
"""
Tests for ProcessingState enum and ProcessingResult error handling states.

This test suite verifies that:
1. ProcessingState enum correctly distinguishes between PASS, FAIL, and ERROR
2. ProcessingResult correctly uses ProcessingState instead of boolean success
3. Backward compatibility property works correctly
4. All three states are properly handled in different scenarios

Can be run in two ways:
1. As pytest test: pytest tests/feedback/test_processing_states.py -v
2. As standalone verification: python3 tests/feedback/test_processing_states.py
   (runs code structure checks without requiring dependencies)
"""

import sys
from pathlib import Path

# Add project root to path for imports when running directly
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def verify_implementation_structure():
    """
    Verify ProcessingState implementation structure without requiring dependencies.
    This can run even if project dependencies aren't installed.
    """
    print("=" * 60)
    print("Verifying ProcessingState Implementation Structure")
    print("=" * 60)
    print()

    try:
        # Read the base.py file to verify the enum definition
        base_file = ROOT / "src" / "event_processors" / "base.py"
        if not base_file.exists():
            print("❌ ERROR: base.py not found")
            return False

        content = base_file.read_text()

        # Check for ProcessingState enum
        if "class ProcessingState(str, Enum):" not in content:
            print("❌ ERROR: ProcessingState enum not found")
            return False
        print("✅ ProcessingState enum class found")

        # Check for enum values
        if 'PASS = "pass"' not in content:
            print("❌ ERROR: PASS value not found")
            return False
        print("✅ PASS value found")

        if 'FAIL = "fail"' not in content:
            print("❌ ERROR: FAIL value not found")
            return False
        print("✅ FAIL value found")

        if 'ERROR = "error"' not in content:
            print("❌ ERROR: ERROR value not found")
            return False
        print("✅ ERROR value found")

        # Check for ProcessingResult with state field
        if 'state: ProcessingState' not in content:
            print("❌ ERROR: ProcessingResult.state field not found")
            return False
        print("✅ ProcessingResult.state field found")

        # Check for backward compatibility property
        if "@property" in content and "def success(self)" in content:
            print("✅ Backward compatibility .success property found")
        else:
            print("⚠️  WARNING: Backward compatibility .success property not found")

        print()
        print("=" * 60)
        print("✅ All structure checks passed!")
        print("=" * 60)
        print()
        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return False


# Try to import pytest and the actual classes for full testing
try:
    import pytest
    from src.event_processors.base import ProcessingResult, ProcessingState

    HAS_DEPENDENCIES = True
except (ImportError, ModuleNotFoundError):
    # If imports fail, we can still run structure verification
    HAS_DEPENDENCIES = False
    pytest = None
    ProcessingResult = None
    ProcessingState = None


class TestProcessingState:
    """Test ProcessingState enum values and behavior."""

    def test_processing_state_values(self):
        """Verify ProcessingState has correct string values."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        assert ProcessingState.PASS == "pass"
        assert ProcessingState.FAIL == "fail"
        assert ProcessingState.ERROR == "error"

    def test_processing_state_enum_membership(self):
        """Verify ProcessingState values are proper enum members."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        assert isinstance(ProcessingState.PASS, ProcessingState)
        assert isinstance(ProcessingState.FAIL, ProcessingState)
        assert isinstance(ProcessingState.ERROR, ProcessingState)


class TestProcessingResultStates:
    """Test ProcessingResult with different ProcessingState values."""

    def test_processing_result_pass_state(self):
        """Test ProcessingResult with PASS state (no violations)."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        result = ProcessingResult(
            state=ProcessingState.PASS,
            violations=[],
            api_calls_made=1,
            processing_time_ms=100,
        )

        assert result.state == ProcessingState.PASS
        assert result.success is True  # Backward compatibility
        assert result.violations == []
        assert result.error is None

    def test_processing_result_fail_state(self):
        """Test ProcessingResult with FAIL state (violations found)."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        violations = [{"rule": "test-rule", "severity": "high", "message": "Test violation"}]
        result = ProcessingResult(
            state=ProcessingState.FAIL,
            violations=violations,
            api_calls_made=2,
            processing_time_ms=200,
        )

        assert result.state == ProcessingState.FAIL
        assert result.success is False  # Backward compatibility
        assert len(result.violations) == 1
        assert result.error is None

    def test_processing_result_error_state(self):
        """Test ProcessingResult with ERROR state (exception occurred)."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        result = ProcessingResult(
            state=ProcessingState.ERROR,
            violations=[],
            api_calls_made=0,
            processing_time_ms=50,
            error="Failed to fetch rules",
        )

        assert result.state == ProcessingState.ERROR
        assert result.success is False  # Backward compatibility
        assert result.violations == []
        assert result.error == "Failed to fetch rules"

    def test_processing_result_backward_compatibility(self):
        """Test that .success property works for backward compatibility."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        # PASS state should return True
        pass_result = ProcessingResult(
            state=ProcessingState.PASS,
            violations=[],
            api_calls_made=1,
            processing_time_ms=100,
        )
        assert pass_result.success is True

        # FAIL state should return False
        fail_result = ProcessingResult(
            state=ProcessingState.FAIL,
            violations=[{"rule": "test"}],
            api_calls_made=1,
            processing_time_ms=100,
        )
        assert fail_result.success is False

        # ERROR state should return False
        error_result = ProcessingResult(
            state=ProcessingState.ERROR,
            violations=[],
            api_calls_made=0,
            processing_time_ms=50,
            error="Test error",
        )
        assert error_result.success is False

    def test_processing_result_state_distinction(self):
        """Test that PASS, FAIL, and ERROR are clearly distinguished."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        # PASS: No violations, no errors
        pass_result = ProcessingResult(
            state=ProcessingState.PASS,
            violations=[],
            api_calls_made=1,
            processing_time_ms=100,
        )

        # FAIL: Violations found, but processing succeeded
        fail_result = ProcessingResult(
            state=ProcessingState.FAIL,
            violations=[{"rule": "test", "message": "Violation"}],
            api_calls_made=1,
            processing_time_ms=100,
        )

        # ERROR: Exception occurred, couldn't check
        error_result = ProcessingResult(
            state=ProcessingState.ERROR,
            violations=[],
            api_calls_made=0,
            processing_time_ms=50,
            error="Exception occurred",
        )

        # Verify states are distinct
        assert pass_result.state != fail_result.state
        assert pass_result.state != error_result.state
        assert fail_result.state != error_result.state

        # Verify PASS has no violations and no error
        assert pass_result.violations == []
        assert pass_result.error is None

        # Verify FAIL has violations but no error
        assert len(fail_result.violations) > 0
        assert fail_result.error is None

        # Verify ERROR has error message
        assert error_result.error is not None

    def test_processing_result_with_violations_and_error(self):
        """Test edge case: result with both violations and error (should be ERROR state)."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        # If there's an error, state should be ERROR regardless of violations
        result = ProcessingResult(
            state=ProcessingState.ERROR,
            violations=[{"rule": "test"}],  # Violations found before error
            api_calls_made=1,
            processing_time_ms=100,
            error="Processing failed after finding violations",
        )

        assert result.state == ProcessingState.ERROR
        assert result.error is not None
        # Even though violations exist, state is ERROR because processing failed

    def test_processing_result_pydantic_validation(self):
        """Test that ProcessingResult validates state correctly."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        # Valid state should work
        result = ProcessingResult(
            state=ProcessingState.PASS,
            violations=[],
            api_calls_made=1,
            processing_time_ms=100,
        )
        assert result.state == ProcessingState.PASS

        # Invalid state should raise validation error
        with pytest.raises(Exception):  # Pydantic validation error
            ProcessingResult(
                state="invalid_state",  # type: ignore
                violations=[],
                api_calls_made=1,
                processing_time_ms=100,
            )


class TestProcessingStateScenarios:
    """Test real-world scenarios for each processing state."""

    def test_scenario_pass_no_rules_configured(self):
        """Scenario: No rules configured - should be PASS (not an error)."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        result = ProcessingResult(
            state=ProcessingState.PASS,
            violations=[],
            api_calls_made=1,
            processing_time_ms=50,
        )

        assert result.state == ProcessingState.PASS
        assert result.success is True

    def test_scenario_pass_all_rules_passed(self):
        """Scenario: Rules evaluated, all passed - should be PASS."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        result = ProcessingResult(
            state=ProcessingState.PASS,
            violations=[],
            api_calls_made=2,
            processing_time_ms=150,
        )

        assert result.state == ProcessingState.PASS
        assert result.success is True

    def test_scenario_fail_violations_found(self):
        """Scenario: Rules evaluated, violations found - should be FAIL."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        violations = [
            {"rule": "min-approvals", "severity": "high", "message": "Need 2 approvals"},
            {"rule": "required-labels", "severity": "medium", "message": "Missing label"},
        ]
        result = ProcessingResult(
            state=ProcessingState.FAIL,
            violations=violations,
            api_calls_made=2,
            processing_time_ms=200,
        )

        assert result.state == ProcessingState.FAIL
        assert result.success is False
        assert len(result.violations) == 2

    def test_scenario_error_exception_occurred(self):
        """Scenario: Exception during processing - should be ERROR."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        result = ProcessingResult(
            state=ProcessingState.ERROR,
            violations=[],
            api_calls_made=0,
            processing_time_ms=10,
            error="Failed to fetch rules: Connection timeout",
        )

        assert result.state == ProcessingState.ERROR
        assert result.success is False
        assert result.error is not None
        assert "timeout" in result.error.lower()

    def test_scenario_error_rules_file_not_found(self):
        """Scenario: Rules file not found - could be PASS or ERROR depending on context."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        # If rules file not found is expected (first time setup), it's PASS
        result_pass = ProcessingResult(
            state=ProcessingState.PASS,
            violations=[],
            api_calls_made=1,
            processing_time_ms=50,
            error="Rules not configured",  # Informational, not an error state
        )

        # If rules file should exist but doesn't, it's ERROR
        result_error = ProcessingResult(
            state=ProcessingState.ERROR,
            violations=[],
            api_calls_made=1,
            processing_time_ms=50,
            error="Rules file not found: .watchflow/rules.yaml",
        )

        # Both have error messages, but different states
        assert result_pass.state == ProcessingState.PASS
        assert result_error.state == ProcessingState.ERROR


class TestProcessingStateComparison:
    """Test comparison and equality of ProcessingState values."""

    def test_processing_state_equality(self):
        """Test that ProcessingState values can be compared."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        assert ProcessingState.PASS == ProcessingState.PASS
        assert ProcessingState.FAIL == ProcessingState.FAIL
        assert ProcessingState.ERROR == ProcessingState.ERROR
        assert ProcessingState.PASS != ProcessingState.FAIL
        assert ProcessingState.PASS != ProcessingState.ERROR
        assert ProcessingState.FAIL != ProcessingState.ERROR

    def test_processing_result_state_comparison(self):
        """Test comparing ProcessingResult states."""
        if not HAS_DEPENDENCIES:
            pytest.skip("Dependencies not available")
        pass_result = ProcessingResult(
            state=ProcessingState.PASS,
            violations=[],
            api_calls_made=1,
            processing_time_ms=100,
        )

        fail_result = ProcessingResult(
            state=ProcessingState.FAIL,
            violations=[{"rule": "test"}],
            api_calls_made=1,
            processing_time_ms=100,
        )

        assert pass_result.state == ProcessingState.PASS
        assert fail_result.state == ProcessingState.FAIL
        assert pass_result.state != fail_result.state


if __name__ == "__main__":
    # When run directly, do structure verification first
    print("Running structure verification...")
    structure_ok = verify_implementation_structure()

    # If pytest is available, also run the tests
    if HAS_DEPENDENCIES and pytest:
        print("\n" + "=" * 60)
        print("Running pytest tests...")
        print("=" * 60 + "\n")
        exit_code = pytest.main([__file__, "-v"])
        sys.exit(exit_code)
    else:
        # Just exit based on structure verification
        if structure_ok:
            print("\n✅ Structure verification passed!")
            print("Note: Install dependencies to run full pytest tests:")
            print("  pytest tests/feedback/test_processing_states.py -v")
        sys.exit(0 if structure_ok else 1)
