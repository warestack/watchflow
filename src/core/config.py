import json
import os
from dataclasses import dataclass

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
class AgentAIConfig:
    """Per-agent AI configuration."""

    max_tokens: int = 4096
    temperature: float = 0.1


@dataclass
class AIConfig:
    """AI provider configuration."""

    api_key: str
    provider: str = "openai"
    max_tokens: int = 4096
    temperature: float = 0.1
    # Provider-specific model fields
    openai_model: str | None = None
    bedrock_model_id: str | None = None
    vertex_ai_model: str | None = None
    # Optional provider-specific fields
    # AWS Bedrock
    bedrock_region: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_profile: str | None = None
    # GCP Model Garden
    gcp_project: str | None = None
    gcp_location: str | None = None
    gcp_service_account_key_base64: str | None = None
    # Per-agent configurations
    engine_agent: AgentAIConfig | None = None
    feasibility_agent: AgentAIConfig | None = None
    acknowledgment_agent: AgentAIConfig | None = None

    def get_model_for_provider(self, provider: str) -> str:
        """Get the appropriate model for the given provider with fallbacks."""
        provider = provider.lower()

        if provider == "openai":
            return self.openai_model or "gpt-4.1-mini"
        elif provider == "bedrock":
            return self.bedrock_model_id or "anthropic.claude-3-sonnet-20240229-v1:0"
        elif provider in ["vertex_ai", "garden", "model_garden", "gcp", "vertex", "vertexai"]:
            # Support both Gemini and Claude models in Vertex AI
            return self.vertex_ai_model or "gemini-pro"
        else:
            return "gpt-4.1-mini"  # Ultimate fallback

    def get_max_tokens_for_agent(self, agent: str | None = None) -> int:
        """Get max tokens for agent with fallback to global config."""
        if agent and hasattr(self, agent):
            agent_config = getattr(self, agent)
            if agent_config and hasattr(agent_config, "max_tokens"):
                return agent_config.max_tokens
        return self.max_tokens

    def get_temperature_for_agent(self, agent: str | None = None) -> float:
        """Get temperature for agent with fallback to global config."""
        if agent and hasattr(self, agent):
            agent_config = getattr(self, agent)
            if agent_config and hasattr(agent_config, "temperature"):
                return agent_config.temperature
        return self.temperature


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

    headers: list[str]
    origins: list[str]


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
            app_id=os.getenv("APP_CLIENT_ID_GITHUB", ""),
            app_client_secret=os.getenv("APP_CLIENT_SECRET_GITHUB", ""),
            private_key=os.getenv("PRIVATE_KEY_BASE64_GITHUB", ""),
            webhook_secret=os.getenv("WEBHOOK_SECRET_GITHUB", ""),
        )

        self.ai = AIConfig(
            provider=os.getenv("AI_PROVIDER", "openai"),
            api_key=os.getenv("OPENAI_API_KEY", ""),
            max_tokens=int(os.getenv("AI_MAX_TOKENS", "4096")),
            temperature=float(os.getenv("AI_TEMPERATURE", "0.1")),
            # Provider-specific model fields
            openai_model=os.getenv("OPENAI_MODEL"),
            bedrock_model_id=os.getenv("BEDROCK_MODEL_ID"),
            vertex_ai_model=os.getenv("VERTEX_AI_MODEL") or os.getenv("MODEL_GARDEN_MODEL"),  # Support legacy name
            # AWS Bedrock configuration
            bedrock_region=os.getenv("BEDROCK_REGION"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_profile=os.getenv("AWS_PROFILE"),
            # GCP Model Garden configuration
            gcp_project=os.getenv("GCP_PROJECT_ID"),
            gcp_location=os.getenv("GCP_LOCATION"),
            gcp_service_account_key_base64=os.getenv("GCP_SERVICE_ACCOUNT_KEY_BASE64"),
            # Per-agent configurations
            engine_agent=AgentAIConfig(
                max_tokens=int(os.getenv("AI_ENGINE_MAX_TOKENS", "8000")),
                temperature=float(os.getenv("AI_ENGINE_TEMPERATURE", "0.1")),
            ),
            feasibility_agent=AgentAIConfig(
                max_tokens=int(os.getenv("AI_FEASIBILITY_MAX_TOKENS", "4096")),
                temperature=float(os.getenv("AI_FEASIBILITY_TEMPERATURE", "0.1")),
            ),
            acknowledgment_agent=AgentAIConfig(
                max_tokens=int(os.getenv("AI_ACKNOWLEDGMENT_MAX_TOKENS", "2000")),
                temperature=float(os.getenv("AI_ACKNOWLEDGMENT_TEMPERATURE", "0.1")),
            ),
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
        cors_origins = os.getenv(
            "CORS_ORIGINS",
            '["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5500", "https://warestack.github.io", "https://watchflow.dev"]',
        )

        try:
            self.cors = CORSConfig(
                headers=json.loads(cors_headers),
                origins=json.loads(cors_origins),
            )
        except json.JSONDecodeError:
            # Fallback to default values if JSON parsing fails
            self.cors = CORSConfig(
                headers=["*"],
                origins=[
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                    "http://localhost:5500",
                    "https://warestack.github.io",
                    "https://watchflow.dev",
                ],
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
            errors.append("WEBHOOK_SECRET_GITHUB is required")

        if self.ai.provider == "openai" and not self.ai.api_key:
            errors.append("OPENAI_API_KEY is required for OpenAI provider")
        if self.ai.provider == "bedrock":
            # Bedrock credentials are read from AWS environment/IMDS; encourage region/model hints
            if not self.ai.bedrock_model_id:
                errors.append("BEDROCK_MODEL_ID is required for Bedrock provider")
        if self.ai.provider in {"vertex_ai", "garden", "vertex", "vertexai", "model_garden", "gcp"}:
            # Vertex AI typically uses ADC; project/location optional but recommended
            if not self.ai.vertex_ai_model:
                errors.append("VERTEX_AI_MODEL is required for Google Vertex AI provider")

        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")

        return True


# Global config instance
config = Config()
