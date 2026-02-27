"""Conditions package for rule validation.

This package contains modular condition classes extracted from validators.py.
Each module focuses on a specific domain of validation.
"""

from src.rules.conditions.access_control import (
    AuthorTeamCondition,
    CodeOwnersCondition,
    PathHasCodeOwnerCondition,
    ProtectedBranchesCondition,
    RequireCodeOwnerReviewersCondition,
)
from src.rules.conditions.base import BaseCondition
from src.rules.conditions.filesystem import (
    FilePatternCondition,
    MaxFileSizeCondition,
    MaxPrLocCondition,
    TestCoverageCondition,
)
from src.rules.conditions.pull_request import (
    DiffPatternCondition,
    MinDescriptionLengthCondition,
    RequiredLabelsCondition,
    RequireLinkedIssueCondition,
    SecurityPatternCondition,
    TitlePatternCondition,
    UnresolvedCommentsCondition,
)
from src.rules.conditions.temporal import (
    AllowedHoursCondition,
    CommentResponseTimeCondition,
    DaysCondition,
    WeekendCondition,
)
from src.rules.conditions.workflow import WorkflowDurationCondition

__all__ = [
    # Base
    "BaseCondition",
    # Filesystem
    "FilePatternCondition",
    "MaxFileSizeCondition",
    "MaxPrLocCondition",
    "TestCoverageCondition",
    # Pull Request
    "TitlePatternCondition",
    "MinDescriptionLengthCondition",
    "RequireLinkedIssueCondition",
    "RequiredLabelsCondition",
    "DiffPatternCondition",
    "SecurityPatternCondition",
    "UnresolvedCommentsCondition",
    # Access Control
    "AuthorTeamCondition",
    "CodeOwnersCondition",
    "PathHasCodeOwnerCondition",
    "ProtectedBranchesCondition",
    "RequireCodeOwnerReviewersCondition",
    # Temporal
    "AllowedHoursCondition",
    "CommentResponseTimeCondition",
    "DaysCondition",
    "WeekendCondition",
    # Workflow
    "WorkflowDurationCondition",
]
