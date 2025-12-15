from src.agents.repository_analysis_agent.models import RepositoryAnalysisRequest, parse_github_repo_identifier


def test_parse_github_repo_identifier_normalizes_url():
    assert parse_github_repo_identifier("https://github.com/owner/repo.git") == "owner/repo"
    assert parse_github_repo_identifier("owner/repo/") == "owner/repo"


def test_repository_analysis_request_normalizes_from_url():
    request = RepositoryAnalysisRequest(repository_url="https://github.com/owner/repo.git")
    assert request.repository_full_name == "owner/repo"

