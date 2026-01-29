"""Conditions package for rule validation.

This package contains modular condition classes extracted from validators.py.
Each module focuses on a specific domain of validation.
"""

from src.rules.conditions.access_control import (
    AuthorTeamCondition,
    CodeOwnersCondition,
    ProtectedBranchesCondition,
)
from src.rules.conditions.base import BaseCondition
from src.rules.conditions.filesystem import FilePatternCondition, MaxFileSizeCondition
from src.rules.conditions.pull_request import (
    MinDescriptionLengthCondition,
    RequiredLabelsCondition,
    TitlePatternCondition,
)
from src.rules.conditions.temporal import (
    AllowedHoursCondition,
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
    # Pull Request
    "TitlePatternCondition",
    "MinDescriptionLengthCondition",
    "RequiredLabelsCondition",
    # Access Control
    "AuthorTeamCondition",
    "CodeOwnersCondition",
    "ProtectedBranchesCondition",
    # Temporal
    "AllowedHoursCondition",
    "DaysCondition",
    "WeekendCondition",
    # Workflow
    "WorkflowDurationCondition",
]
