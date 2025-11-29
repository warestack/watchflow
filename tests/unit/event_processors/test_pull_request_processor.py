from src.event_processors.pull_request import PullRequestProcessor


def test_summarize_files_for_llm_truncates_patch():
    files = [
        {
            "filename": "packages/core/src/vector-query.ts",
            "status": "modified",
            "additions": 10,
            "deletions": 2,
            "patch": "+throw new Error('invalid filter')\n+return []\n+console.log('debug')",
        }
    ]

    summary = PullRequestProcessor._summarize_files_for_llm(files, max_files=1, max_patch_lines=2)

    assert "- packages/core/src/vector-query.ts (modified, +10/-2)" in summary
    assert "throw new Error" in summary
    assert "console.log" not in summary  # truncated beyond max_patch_lines
    assert "... (diff truncated)" in summary


def test_summarize_files_for_llm_handles_no_files():
    summary = PullRequestProcessor._summarize_files_for_llm([])

    assert summary == ""

