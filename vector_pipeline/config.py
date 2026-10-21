import os
import tomllib
from pathlib import Path
from dataclasses import dataclass


def settings():
    with Path(__file__).with_name("settings.toml").open("rb") as stream:
        return tomllib.load(stream)


@dataclass(frozen=True)
class EmbeddingConfig:
    region: str
    model: str
    dimensions: int

    @classmethod
    def from_env(cls):
        config = cls(
            os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION") or settings()["aws"]["region"],
            os.getenv("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"),
            int(os.getenv("EMBEDDING_DIMENSIONS", "1024")),
        )
        if not config.region:
            raise ValueError("BEDROCK_REGION 또는 AWS_REGION을 명시하세요. 리전을 추정하지 않습니다.")
        if config.model != "amazon.titan-embed-text-v2:0":
            raise ValueError("현재 임베딩 어댑터는 Titan Text Embeddings V2만 지원합니다.")
        if config.dimensions not in (256, 512, 1024):
            raise ValueError("EMBEDDING_DIMENSIONS는 256, 512, 1024 중 하나여야 합니다.")
        return config

    @property
    def version(self):
        return f"{self.model}:dim={self.dimensions}:normalize=true"
