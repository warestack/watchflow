import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.agents.repository_analysis_agent.models import AnalysisState, RuleRecommendation
from src.agents.repository_analysis_agent.prompts import REPOSITORY_ANALYSIS_SYSTEM_PROMPT, RULE_GENERATION_USER_PROMPT
from src.integrations.github.api import github_client
from src.integrations.providers.factory import get_chat_model

logger = logging.getLogger(__name__)


async def fetch_repository_metadata(state: AnalysisState) -> dict:
    """
    Step 1: Gather raw signals from GitHub (Public or Private).
    This node populates the 'Shared Memory' (State) with facts about the repo.
    """
    repo = state.repo_full_name
    if not repo:
        raise ValueError("Repository full name is missing in state.")

    logger.info(f"Analyzing structure for: {repo}")

    # 1. Fetch File Tree (Root)
    try:
        files = await github_client.list_directory_any_auth(repo_full_name=repo, path="")
    except Exception as e:
        logger.error(f"Failed to fetch file tree for {repo}: {e}")
        files = []

    file_names = [f["name"] for f in files] if files else []

    # 2. Heuristic Language Detection
    languages = []
    if "pom.xml" in file_names:
        languages.append("Java")
    if "package.json" in file_names:
        languages.append("JavaScript/TypeScript")
    if "requirements.txt" in file_names or "pyproject.toml" in file_names:
        languages.append("Python")
    if "go.mod" in file_names:
        languages.append("Go")
    if "Cargo.toml" in file_names:
        languages.append("Rust")

    # 3. Check for CI/CD presence
    has_ci = ".github" in file_names

    # 4. Fetch Documentation Snippets (for Context)
    readme_content = ""
    target_files = ["README.md", "readme.md", "CONTRIBUTING.md"]
    for target in target_files:
        if target in file_names:
            content = await github_client.get_file_content(repo_full_name=repo, file_path=target, installation_id=None)
            if content:
                readme_content = content[:2000]
                break

    # 5. CODEOWNERS detection (root, .github/, docs/)
    codeowners_paths = ["CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"]
    has_codeowners = False
    for copath in codeowners_paths:
        try:
            co_content = await github_client.get_file_content(
                repo_full_name=repo, file_path=copath, installation_id=None
            )
            if co_content and len(co_content.strip()) > 0:
                has_codeowners = True
                break
        except Exception:
            continue

    # 6. Analyze workflows for CI patterns
    workflow_patterns = []
    try:
        workflow_files = await github_client.list_directory_any_auth(repo_full_name=repo, path=".github/workflows")
        for wf in workflow_files:
            wf_name = wf["name"]
            if wf_name.endswith(".yml") or wf_name.endswith(".yaml"):
                content = await github_client.get_file_content(
                    repo_full_name=repo, file_path=f".github/workflows/{wf_name}", installation_id=None
                )
                if content:
                    if "pytest" in content:
                        workflow_patterns.append("pytest")
                    if "actions/checkout" in content:
                        workflow_patterns.append("actions/checkout")
                    if "deploy" in content:
                        workflow_patterns.append("deploy")
    except Exception as e:
        logger.warning(f"Workflow analysis failed for {repo}: {e}")

    logger.info(
        f"Metadata gathered for {repo}: {len(file_names)} files, Langs: {languages}, CODEOWNERS: {has_codeowners}, Workflows: {workflow_patterns}"
    )

    return {
        "file_tree": file_names,
        "detected_languages": languages,
        "has_ci": has_ci,
        "readme_content": readme_content,
        "has_codeowners": has_codeowners,
        "workflow_patterns": workflow_patterns,
    }


async def generate_rule_recommendations(state: AnalysisState) -> dict:
    """
    Step 2: Send gathered signals to LLM to generate governance rules.
    """
    logger.info("Generating rules via LLM...")

    repo_name = state.repo_full_name or "unknown/repo"
    languages = state.detected_languages
    has_ci = state.has_ci
    file_tree = state.file_tree
    readme_content = state.readme_content or ""

    # 1. Construct Prompt
    # We format the prompt with the specific context of this repository
    user_prompt = RULE_GENERATION_USER_PROMPT.format(
        repo_name=repo_name,
        languages=", ".join(languages) if languages else "Unknown",
        has_ci=str(has_ci),
        file_count=len(file_tree),
        file_tree_snippet="\n".join(file_tree[:25]),  # Provide top 25 files for context
        docs_snippet=readme_content[:1000],  # Truncated context
    )

    # 2. Initialize LLM
    # We use the factory to respect project settings (provider, temperature)
    try:
        llm = get_chat_model(agent="repository_analysis")

        # 3. Structured Output Enforcement
        # We define a wrapper model to ensure we get a list of recommendations
        # Note: LangChain's with_structured_output is preferred over raw JSON parsing
        class RecommendationsList(AnalysisState):
            # We strictly want the list, reusing the model definition
            recommendations: list[RuleRecommendation]

        structured_llm = llm.with_structured_output(RecommendationsList)

        response = await structured_llm.ainvoke(
            [SystemMessage(content=REPOSITORY_ANALYSIS_SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
        )

        # The response is already a Pydantic object (RecommendationsList or similar)
        # We extract the list of recommendations
        valid_recs = response.recommendations if hasattr(response, "recommendations") else []

        logger.info(f"LLM generated {len(valid_recs)} recommendations for {repo_name}")
        return {"recommendations": valid_recs}

    except Exception as e:
        logger.error(f"LLM Generation Failed for {repo_name}: {e}", exc_info=True)

        # Fallback: Return a Safe-Mode Rule so the UI doesn't break
        # This complies with the "Robust Error Handling" requirement
        fallback_rule = RuleRecommendation(
            key="manual_review_required",
            name="Manual Governance Review",
            description="AI analysis could not complete. Please review repository manually.",
            severity="low",
            category="system",
            reasoning=f"Automated analysis failed due to: {str(e)}",
        )
        return {"recommendations": [fallback_rule], "error": str(e)}
