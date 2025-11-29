import asyncio

import pytest

from src.rules.validators import (
    DiffPatternCondition,
    RelatedTestsCondition,
    RequiredFieldInDiffCondition,
)


@pytest.mark.asyncio
async def test_diff_pattern_condition_requirements_met():
    condition = DiffPatternCondition()
    event = {
        "files": [
            {
                "filename": "packages/core/src/vector-query.ts",
                "status": "modified",
                "patch": "+throw new Error('invalid filter')\n+return []\n",
            }
        ]
    }

    params = {
        "file_patterns": ["packages/core/src/**/vector-query.ts"],
        "require_patterns": ["throw\\s+new\\s+Error"],
    }

    assert await condition.validate(params, event)


@pytest.mark.asyncio
async def test_diff_pattern_condition_missing_requirement():
    condition = DiffPatternCondition()
    event = {
        "files": [
            {
                "filename": "packages/core/src/vector-query.ts",
                "status": "modified",
                "patch": "+return []\n",
            }
        ]
    }

    params = {
        "file_patterns": ["packages/core/src/**/vector-query.ts"],
        "require_patterns": ["throw\\s+new\\s+Error"],
    }

    assert not await condition.validate(params, event)


@pytest.mark.asyncio
async def test_related_tests_condition_requires_test_files():
    condition = RelatedTestsCondition()
    event = {
        "files": [
            {
                "filename": "packages/core/src/vector-query.ts",
                "status": "modified",
            },
            {
                "filename": "tests/vector-query.test.ts",
                "status": "modified",
            },
        ]
    }

    params = {
        "source_patterns": ["packages/core/src/**"],
        "test_patterns": ["tests/**"],
    }

    assert await condition.validate(params, event)


@pytest.mark.asyncio
async def test_related_tests_condition_flags_missing_tests():
    condition = RelatedTestsCondition()
    event = {
        "files": [
            {
                "filename": "packages/core/src/vector-query.ts",
                "status": "modified",
            }
        ]
    }

    params = {
        "source_patterns": ["packages/core/src/**"],
        "test_patterns": ["tests/**"],
    }

    assert not await condition.validate(params, event)


@pytest.mark.asyncio
async def test_required_field_in_diff_condition():
    condition = RequiredFieldInDiffCondition()
    event = {
        "files": [
            {
                "filename": "packages/core/src/agent/foo/agent.py",
                "status": "modified",
                "patch": "+class FooAgent:\n+    description = \"foo\"\n",
            }
        ]
    }

    params = {
        "file_patterns": ["packages/core/src/agent/**"],
        "required_text": "description",
    }

    assert await condition.validate(params, event)


@pytest.mark.asyncio
async def test_required_field_in_diff_condition_missing_text():
    condition = RequiredFieldInDiffCondition()
    event = {
        "files": [
            {
                "filename": "packages/core/src/agent/foo/agent.py",
                "status": "modified",
                "patch": "+class FooAgent:\n+    pass\n",
            }
        ]
    }

    params = {
        "file_patterns": ["packages/core/src/agent/**"],
        "required_text": "description",
    }

    assert not await condition.validate(params, event)

