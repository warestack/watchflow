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
from src.rules.conditions.access_control_advanced import (
    CrossTeamApprovalCondition,
    NoSelfApprovalCondition,
)
from src.rules.conditions.base import BaseCondition
from src.rules.conditions.compliance import (
    ChangelogRequiredCondition,
    SignedCommitsCondition,
)
from src.rules.conditions.filesystem import (
    FilePatternCondition,
    MaxFileSizeCondition,
    MaxPrLocCondition,
    TestCoverageCondition,
)
from src.rules.conditions.llm_assisted import DescriptionDiffAlignmentCondition
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
    # Access Control - Advanced
    "NoSelfApprovalCondition",
    "CrossTeamApprovalCondition",
    # Compliance
    "SignedCommitsCondition",
    "ChangelogRequiredCondition",
    # LLM-assisted
    "DescriptionDiffAlignmentCondition",
    # Temporal
    "AllowedHoursCondition",
    "CommentResponseTimeCondition",
    "DaysCondition",
    "WeekendCondition",
    # Workflow
    "WorkflowDurationCondition",
]
