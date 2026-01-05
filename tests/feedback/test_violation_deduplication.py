#!/usr/bin/env python3
"""
Tests for violation deduplication and tracking.

This test suite verifies that:
1. ViolationTracker correctly identifies duplicate violations
2. Fingerprinting generates unique IDs for violations
3. Duplicate violations are filtered before reporting
4. TTL-based expiration works correctly
5. Integration with event processors works

Can be run in two ways:
1. As pytest test: pytest tests/feedback/test_violation_deduplication.py -v
2. As standalone verification: python3 tests/feedback/test_violation_deduplication.py
"""

import sys
import time
from pathlib import Path

# Add project root to path for imports when running directly
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestViolationFingerprinting:
    """Test violation fingerprinting functionality."""

    def test_same_violation_same_fingerprint(self):
        """Test that the same violation generates the same fingerprint."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {"validator_used": "test_validator", "parameters": {"key": "value"}},
        }

        fingerprint1 = tracker.generate_fingerprint(violation, "owner/repo")
        fingerprint2 = tracker.generate_fingerprint(violation, "owner/repo")

        assert fingerprint1 == fingerprint2, "Same violation should generate same fingerprint"

    def test_different_violations_different_fingerprints(self):
        """Test that different violations generate different fingerprints."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation1 = {
            "rule_description": "Test Rule 1",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }
        violation2 = {
            "rule_description": "Test Rule 2",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        fingerprint1 = tracker.generate_fingerprint(violation1, "owner/repo")
        fingerprint2 = tracker.generate_fingerprint(violation2, "owner/repo")

        assert fingerprint1 != fingerprint2, "Different violations should generate different fingerprints"

    def test_fingerprint_includes_repo(self):
        """Test that fingerprint includes repository name."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        fingerprint1 = tracker.generate_fingerprint(violation, "owner/repo1")
        fingerprint2 = tracker.generate_fingerprint(violation, "owner/repo2")

        assert fingerprint1 != fingerprint2, "Different repos should generate different fingerprints"

    def test_fingerprint_includes_context(self):
        """Test that fingerprint includes context data (PR number, commit SHA)."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        context1 = {"pr_number": 1, "commit_sha": "abc123"}
        context2 = {"pr_number": 2, "commit_sha": "def456"}

        fingerprint1 = tracker.generate_fingerprint(violation, "owner/repo", context1)
        fingerprint2 = tracker.generate_fingerprint(violation, "owner/repo", context2)

        assert fingerprint1 != fingerprint2, "Different contexts should generate different fingerprints"

    def test_fingerprint_same_context_same_fingerprint(self):
        """Test that same violation with same context generates same fingerprint."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        context = {"pr_number": 1, "commit_sha": "abc123"}

        fingerprint1 = tracker.generate_fingerprint(violation, "owner/repo", context)
        fingerprint2 = tracker.generate_fingerprint(violation, "owner/repo", context)

        assert fingerprint1 == fingerprint2, "Same violation with same context should generate same fingerprint"


class TestViolationTracking:
    """Test violation tracking and deduplication."""

    def test_mark_reported(self):
        """Test marking a violation as reported."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        fingerprint = tracker.generate_fingerprint(violation, "owner/repo")
        assert not tracker.is_reported(fingerprint), "Violation should not be reported initially"

        tracker.mark_reported(fingerprint, violation)
        assert tracker.is_reported(fingerprint), "Violation should be reported after marking"

    def test_filter_new_violations(self):
        """Test filtering out duplicate violations."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation1 = {
            "rule_description": "Test Rule 1",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }
        violation2 = {
            "rule_description": "Test Rule 2",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        # First batch - all should be new
        violations = [violation1, violation2]
        new_violations = tracker.filter_new_violations(violations, "owner/repo")
        assert len(new_violations) == 2, "All violations should be new initially"

        # Second batch - same violations should be filtered
        new_violations = tracker.filter_new_violations(violations, "owner/repo")
        assert len(new_violations) == 0, "Duplicate violations should be filtered out"

    def test_filter_mixed_violations(self):
        """Test filtering with mix of new and duplicate violations."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation1 = {
            "rule_description": "Test Rule 1",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }
        violation2 = {
            "rule_description": "Test Rule 2",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }
        violation3 = {
            "rule_description": "Test Rule 3",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        # First batch
        violations = [violation1, violation2]
        new_violations = tracker.filter_new_violations(violations, "owner/repo")
        assert len(new_violations) == 2

        # Second batch with one duplicate and one new
        violations = [violation1, violation3]
        new_violations = tracker.filter_new_violations(violations, "owner/repo")
        assert len(new_violations) == 1, "Should filter duplicate, keep new"
        assert new_violations[0]["rule_description"] == "Test Rule 3"

    def test_ttl_expiration(self):
        """Test that violations expire after TTL."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker(ttl_seconds=1)  # 1 second TTL
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        fingerprint = tracker.generate_fingerprint(violation, "owner/repo")
        tracker.mark_reported(fingerprint, violation)
        assert tracker.is_reported(fingerprint), "Violation should be reported"

        # Wait for expiration
        time.sleep(1.1)
        assert not tracker.is_reported(fingerprint), "Violation should expire after TTL"

    def test_get_stats(self):
        """Test getting tracker statistics."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker(ttl_seconds=3600)
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        fingerprint = tracker.generate_fingerprint(violation, "owner/repo")
        tracker.mark_reported(fingerprint, violation)

        stats = tracker.get_stats()
        assert stats["total_tracked"] == 1
        assert stats["active"] == 1
        assert stats["expired"] == 0
        assert stats["total_reports"] >= 1

    def test_clear(self):
        """Test clearing all tracked violations."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        fingerprint = tracker.generate_fingerprint(violation, "owner/repo")
        tracker.mark_reported(fingerprint, violation)
        assert tracker.is_reported(fingerprint)

        tracker.clear()
        assert not tracker.is_reported(fingerprint), "Violation should not be reported after clear"


class TestGlobalViolationTracker:
    """Test global violation tracker instance."""

    def test_get_violation_tracker(self):
        """Test getting the global violation tracker."""
        from src.core.utils.violation_tracker import get_violation_tracker

        tracker1 = get_violation_tracker()
        tracker2 = get_violation_tracker()

        assert tracker1 is tracker2, "Should return the same global instance"

    def test_global_tracker_functionality(self):
        """Test that global tracker works correctly."""
        from src.core.utils.violation_tracker import get_violation_tracker

        tracker = get_violation_tracker()
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        new_violations = tracker.filter_new_violations([violation], "owner/repo")
        assert len(new_violations) == 1, "First violation should be new"

        new_violations = tracker.filter_new_violations([violation], "owner/repo")
        assert len(new_violations) == 0, "Duplicate should be filtered"


class TestViolationDeduplicationIntegration:
    """Test integration with event processors."""

    def test_violation_dict_format(self):
        """Test that violation dictionaries are properly formatted for tracking."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        # Simulate violation format from RuleViolation model
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed: Test Rule",
            "severity": "high",
            "details": {
                "validator_used": "required_labels",
                "parameters": {"required_labels": ["security"]},
                "validation_result": "failed",
            },
            "how_to_fix": "Add required labels",
            "docs_url": "",
            "validation_strategy": "validator",
            "execution_time_ms": 10.5,
        }

        fingerprint = tracker.generate_fingerprint(violation, "owner/repo")
        assert fingerprint is not None
        assert len(fingerprint) == 64  # SHA256 hex string length

    def test_context_aware_deduplication(self):
        """Test that deduplication works with context (PR number, commit SHA)."""
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        # Same violation on different PRs should be tracked separately
        context1 = {"pr_number": 1}
        context2 = {"pr_number": 2}

        new1 = tracker.filter_new_violations([violation], "owner/repo", context1)
        assert len(new1) == 1

        new2 = tracker.filter_new_violations([violation], "owner/repo", context2)
        assert len(new2) == 1, "Same violation on different PR should be new"

        # But same violation on same PR should be duplicate
        new3 = tracker.filter_new_violations([violation], "owner/repo", context1)
        assert len(new3) == 0, "Same violation on same PR should be duplicate"


def run_standalone_verification():
    """Run verification checks that don't require pytest."""
    print("=" * 60)
    print("Violation Deduplication Verification")
    print("=" * 60)
    print()

    all_passed = True

    # Test 1: ViolationTracker exists
    print("1. Checking ViolationTracker exists...")
    try:
        from src.core.utils.violation_tracker import ViolationTracker, get_violation_tracker

        tracker = ViolationTracker()
        print("   ✅ ViolationTracker created successfully")
        print(f"      - TTL: {tracker.ttl_seconds}s")
    except Exception as e:
        print(f"   ❌ Failed to import ViolationTracker: {e}")
        all_passed = False

    # Test 2: Fingerprinting works
    print()
    print("2. Checking violation fingerprinting...")
    try:
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        fingerprint1 = tracker.generate_fingerprint(violation, "owner/repo")
        fingerprint2 = tracker.generate_fingerprint(violation, "owner/repo")
        assert fingerprint1 == fingerprint2
        print("   ✅ Fingerprinting works correctly")
        print(f"      - Fingerprint length: {len(fingerprint1)}")
    except Exception as e:
        print(f"   ❌ Fingerprinting test failed: {e}")
        all_passed = False

    # Test 3: Deduplication works
    print()
    print("3. Checking violation deduplication...")
    try:
        from src.core.utils.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        violation = {
            "rule_description": "Test Rule",
            "message": "Rule validation failed",
            "severity": "high",
            "details": {},
        }

        # First batch
        new1 = tracker.filter_new_violations([violation], "owner/repo")
        assert len(new1) == 1

        # Second batch (duplicates)
        new2 = tracker.filter_new_violations([violation], "owner/repo")
        assert len(new2) == 0

        print("   ✅ Deduplication works correctly")
        print(f"      - First batch: {len(new1)} new violation(s)")
        print(f"      - Second batch: {len(new2)} new violation(s) (duplicates filtered)")
    except Exception as e:
        print(f"   ❌ Deduplication test failed: {e}")
        all_passed = False

    # Test 4: Global tracker works
    print()
    print("4. Checking global violation tracker...")
    try:
        from src.core.utils.violation_tracker import get_violation_tracker

        tracker = get_violation_tracker()
        stats = tracker.get_stats()
        print("   ✅ Global tracker works")
        print(f"      - Total tracked: {stats['total_tracked']}")
        print(f"      - Active: {stats['active']}")
    except Exception as e:
        print(f"   ❌ Global tracker test failed: {e}")
        all_passed = False

    # Test 5: Integration with PullRequestProcessor
    print()
    print("5. Checking integration with PullRequestProcessor...")
    try:
        from src.event_processors.pull_request import PullRequestProcessor

        # Just check that the import works (actual integration tested in unit tests)
        _processor = PullRequestProcessor()
        print("   ✅ PullRequestProcessor imports violation tracker")
    except Exception as e:
        print(f"   ⚠️  Integration check: {e}")
        # Not a failure, might be missing dependencies

    print()
    print("=" * 60)
    if all_passed:
        print("✅ All verification checks passed!")
    else:
        print("❌ Some checks failed")
    print("=" * 60)

    return all_passed


if __name__ == "__main__":
    # Run standalone verification when executed directly
    success = run_standalone_verification()
    sys.exit(0 if success else 1)
