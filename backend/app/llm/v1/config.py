from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_V1_", env_file=Path(__file__).with_name(".env"), extra="ignore"
    )
    region: str = "us-east-1"
    auth_mode: Literal["ec2_role", "default_chain"] = "ec2_role"
    sonnet_model_id: str = "us.anthropic.claude-sonnet-5-5"
    haiku_model_id: str = "us.anthropic.claude-haiku-5-5"
    default_model: Literal["sonnet", "haiku"] = "haiku"
    embedding_model_id: Literal["amazon.titan-embed-text-v2:0"] = "amazon.titan-embed-text-v2:0"
    embedding_dimensions: Literal[256, 512, 1024] = 1024
    max_output_tokens: int = Field(900, ge=128, le=4096)
    context_chars: int = Field(18000, ge=2000, le=60000)
    top_k: int = Field(3, ge=1, le=8)
    max_distance: float = Field(0.65, ge=0, le=2)
    api_key: SecretStr | None = None

    def model_id(self, alias: str | None) -> str:
        return self.sonnet_model_id if (alias or self.default_model) == "sonnet" else self.haiku_model_id

    @property
    def embedding_version(self) -> str:
        return f"{self.embedding_model_id}:dim={self.embedding_dimensions}:normalize=true"
