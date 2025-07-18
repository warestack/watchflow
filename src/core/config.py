import os
import json
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv


@dataclass
class GitHubConfig:
    """GitHub configuration."""

    app_name: str
    app_id: str
    app_client_secret: str
    private_key: str
    webhook_secret: str
    api_base_url: str = "https://api.github.com"


@dataclass
class AIConfig:
    """AI provider configuration."""

    api_key: str
    provider: str = "openai"
    model: str = "gpt-4.1-mini"
    max_tokens: int = 4096
    temperature: float = 0.1


@dataclass
class LangSmithConfig:
    """LangSmith configuration for AI agent debugging."""

    tracing_v2: bool = False
    endpoint: str = "https://api.smith.langchain.com"
    api_key: str = ""
    project: str = "watchflow-dev"


@dataclass
class CORSConfig:
    """CORS configuration."""

    headers: List[str]
    origins: List[str]


@dataclass
class RepoConfig:
    """Repo configuration."""

    base_path: str = ".watchflow"
    rules_file: str = "rules.yaml"


@dataclass
class LoggingConfig:
    """Logging configuration."""

    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file_path: str | None = None


# Load environment variables from a .env file located in the same directory as this script.
load_dotenv()


class Config:
    """Main configuration class."""

    def __init__(self):
        self.github = GitHubConfig(
            app_name=os.getenv("APP_NAME_GITHUB", ""),
            app_id=os.getenv("CLIENT_ID_GITHUB", ""),
            app_client_secret=os.getenv("APP_CLIENT_SECRET", ""),
            private_key=os.getenv("PRIVATE_KEY_BASE64_GITHUB", ""),
            webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
        )

        self.ai = AIConfig(
            provider=os.getenv("AI_PROVIDER", "openai"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            model=os.getenv("AI_MODEL", "gpt-4.1-mini"),
            max_tokens=int(os.getenv("AI_MAX_TOKENS", "4096")),
            temperature=float(os.getenv("AI_TEMPERATURE", "0.1")),
        )

        # LangSmith configuration
        self.langsmith = LangSmithConfig(
            tracing_v2=os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true",
            endpoint=os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"),
            api_key=os.getenv("LANGCHAIN_API_KEY", ""),
            project=os.getenv("LANGCHAIN_PROJECT", "watchflow-dev"),
        )

        # CORS configuration
        cors_headers = os.getenv("CORS_HEADERS", '["*"]')
        cors_origins = os.getenv("CORS_ORIGINS", '["http://localhost:3000", "http://127.0.0.1:3000"]')
        
        try:
            self.cors = CORSConfig(
                headers=json.loads(cors_headers),
                origins=json.loads(cors_origins),
            )
        except json.JSONDecodeError:
            # Fallback to default values if JSON parsing fails
            self.cors = CORSConfig(
                headers=["*"],
                origins=["http://localhost:3000", "http://127.0.0.1:3000"],
            )

        self.repo_config = RepoConfig(
            base_path=os.getenv("REPO_CONFIG_BASE_PATH", ".watchflow"),
            rules_file=os.getenv("REPO_CONFIG_RULES_FILE", "rules.yaml"),
        )

        self.logging = LoggingConfig(
            level=os.getenv("LOG_LEVEL", "INFO"),
            format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
            file_path=os.getenv("LOG_FILE_PATH"),
        )

        # Development settings
        self.debug = os.getenv("DEBUG", "false").lower() == "true"
        self.environment = os.getenv("ENVIRONMENT", "development")

    def validate(self) -> bool:
        """Validate configuration."""
        errors = []

        if not self.github.app_name:
            errors.append("APP_NAME_GITHUB is required")

        if not self.github.app_id:
            errors.append("CLIENT_ID_GITHUB is required")

        if not self.github.app_client_secret:
            errors.append("APP_CLIENT_SECRET is required")

        if not self.github.private_key:
            errors.append("PRIVATE_KEY_BASE64_GITHUB is required")

        if not self.github.webhook_secret:
            errors.append("GITHUB_WEBHOOK_SECRET is required")

        if self.ai.provider == "openai" and not self.ai.api_key:
            errors.append("OPENAI_API_KEY is required for OpenAI provider")

        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")

        return True


# Global config instance
config = Config()
