"""
Violation tracking and deduplication service.

Tracks reported violations to prevent duplicate reports of the same violation.
Uses fingerprinting to identify unique violations based on rule, context, and event data.
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from src.core.config.settings import config

logger = logging.getLogger(__name__)


class ViolationTracker:
    """
    Tracks reported violations to prevent duplicates.
    
    Uses in-memory storage with TTL-based expiration. Each violation is
    fingerprinted based on its content and context to identify duplicates.
    """

    def __init__(self, ttl_seconds: int = 86400):
        """
        Initialize violation tracker.

        Args:
            ttl_seconds: Time to keep violation records (default: 24 hours)
        """
        # Store: {fingerprint: {"reported_at": timestamp, "count": int}}
        self._reported: dict[str, dict[str, Any]] = {}
        self.ttl_seconds = ttl_seconds
        self._cleanup_threshold = 1000  # Clean up when we have this many entries

    def generate_fingerprint(
        self,
        violation: dict[str, Any],
        repo_full_name: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        Generate a unique fingerprint for a violation.

        The fingerprint is based on:
        - Rule description
        - Violation message
        - Severity
        - Repository
        - Context-specific data (PR number, commit SHA, etc.)

        Args:
            violation: Violation dictionary
            repo_full_name: Repository full name (e.g., "owner/repo")
            context: Optional context data (PR number, commit SHA, etc.)

        Returns:
            SHA256 hash string representing the violation fingerprint
        """
        # Extract key fields that make a violation unique
        rule_description = violation.get("rule_description", "")
        message = violation.get("message", "")
        severity = violation.get("severity", "")
        details = violation.get("details", {})

        # Build fingerprint data
        fingerprint_data = {
            "rule_description": rule_description,
            "message": message,
            "severity": severity,
            "repo": repo_full_name,
            # Include relevant details (but not all, to avoid too much variation)
            "validator": details.get("validator_used", ""),
            "parameters": details.get("parameters", {}),
        }

        # Add context-specific data if provided
        if context:
            # Include PR number if available (violations on same PR are duplicates)
            if "pr_number" in context:
                fingerprint_data["pr_number"] = context["pr_number"]
            # Include commit SHA if available (violations on same commit are duplicates)
            if "commit_sha" in context:
                fingerprint_data["commit_sha"] = context["commit_sha"]
            # Include branch if available
            if "branch" in context:
                fingerprint_data["branch"] = context["branch"]

        # Create deterministic JSON string (sorted keys for consistency)
        json_str = json.dumps(fingerprint_data, sort_keys=True, default=str)

        # Generate SHA256 hash
        fingerprint = hashlib.sha256(json_str.encode("utf-8")).hexdigest()

        logger.debug(f"Generated fingerprint for violation: {fingerprint[:16]}...")
        return fingerprint

    def is_reported(self, fingerprint: str) -> bool:
        """
        Check if a violation has already been reported.

        Args:
            fingerprint: Violation fingerprint

        Returns:
            True if violation was already reported, False otherwise
        """
        if fingerprint not in self._reported:
            return False

        # Check if entry has expired
        entry = self._reported[fingerprint]
        age = datetime.now().timestamp() - entry.get("reported_at", 0)

        if age >= self.ttl_seconds:
            # Entry expired, remove it
            del self._reported[fingerprint]
            logger.debug(f"Violation fingerprint {fingerprint[:16]}... expired and removed")
            return False

        return True

    def mark_reported(
        self,
        fingerprint: str,
        violation: dict[str, Any] | None = None,
    ) -> None:
        """
        Mark a violation as reported.

        Args:
            fingerprint: Violation fingerprint
            violation: Optional violation data for logging
        """
        self._reported[fingerprint] = {
            "reported_at": datetime.now().timestamp(),
            "count": self._reported.get(fingerprint, {}).get("count", 0) + 1,
        }

        if violation:
            rule_desc = violation.get("rule_description", "Unknown")
            logger.debug(f"Marked violation as reported: {rule_desc} (fingerprint: {fingerprint[:16]}...)")

        # Periodic cleanup to prevent memory growth
        if len(self._reported) > self._cleanup_threshold:
            self._cleanup_expired()

    def filter_new_violations(
        self,
        violations: list[dict[str, Any]],
        repo_full_name: str,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Filter out violations that have already been reported.

        Args:
            violations: List of violation dictionaries
            repo_full_name: Repository full name
            context: Optional context data (PR number, commit SHA, etc.)

        Returns:
            List of violations that haven't been reported yet
        """
        new_violations = []
        duplicate_count = 0

        for violation in violations:
            fingerprint = self.generate_fingerprint(violation, repo_full_name, context)

            if self.is_reported(fingerprint):
                duplicate_count += 1
                logger.debug(
                    f"Skipping duplicate violation: {violation.get('rule_description', 'Unknown')} "
                    f"(fingerprint: {fingerprint[:16]}...)"
                )
            else:
                new_violations.append(violation)
                # Mark as reported immediately
                self.mark_reported(fingerprint, violation)

        if duplicate_count > 0:
            logger.info(f"Filtered out {duplicate_count} duplicate violation(s), {len(new_violations)} new violation(s) remain")

        return new_violations

    def _cleanup_expired(self) -> None:
        """Remove expired entries to free memory."""
        now = datetime.now().timestamp()
        expired_keys = [
            fingerprint
            for fingerprint, entry in self._reported.items()
            if (now - entry.get("reported_at", 0)) >= self.ttl_seconds
        ]

        for key in expired_keys:
            del self._reported[key]

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired violation records")

    def get_stats(self) -> dict[str, Any]:
        """
        Get statistics about tracked violations.

        Returns:
            Dictionary with statistics
        """
        now = datetime.now().timestamp()
        active = sum(
            1
            for entry in self._reported.values()
            if (now - entry.get("reported_at", 0)) < self.ttl_seconds
        )

        total_reports = sum(entry.get("count", 0) for entry in self._reported.values())

        return {
            "total_tracked": len(self._reported),
            "active": active,
            "expired": len(self._reported) - active,
            "total_reports": total_reports,
            "ttl_seconds": self.ttl_seconds,
        }

    def clear(self) -> None:
        """Clear all tracked violations (useful for testing)."""
        count = len(self._reported)
        self._reported.clear()
        logger.debug(f"Cleared {count} violation records")


# Global violation tracker instance
_global_tracker: ViolationTracker | None = None


def get_violation_tracker() -> ViolationTracker:
    """
    Get or create the global violation tracker instance.

    Returns:
        Global ViolationTracker instance
    """
    global _global_tracker
    if _global_tracker is None:
        # Use config if available, otherwise default TTL
        ttl = getattr(config, "cache", None)
        if ttl and hasattr(ttl, "global_ttl"):
            # Use cache TTL as a reasonable default for violation tracking
            ttl_seconds = ttl.global_ttl
        else:
            ttl_seconds = 86400  # 24 hours default

        _global_tracker = ViolationTracker(ttl_seconds=ttl_seconds)
        logger.info(f"Initialized violation tracker with TTL: {ttl_seconds}s")

    return _global_tracker

