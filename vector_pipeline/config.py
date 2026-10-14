import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingConfig:
    region: str
    model: str
    dimensions: int

    @classmethod
    def from_env(cls):
        config = cls(
            os.getenv("BEDROCK_REGION", os.getenv("AWS_REGION", "ap-northeast-2")),
            os.getenv("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"),
            int(os.getenv("EMBEDDING_DIMENSIONS", "1024")),
        )
        if config.model != "amazon.titan-embed-text-v2:0":
            raise ValueError("현재 임베딩 어댑터는 Titan Text Embeddings V2만 지원합니다.")
        if config.dimensions not in (256, 512, 1024):
            raise ValueError("EMBEDDING_DIMENSIONS는 256, 512, 1024 중 하나여야 합니다.")
        return config

    @property
    def version(self):
        return f"{self.model}:dim={self.dimensions}:normalize=true"
