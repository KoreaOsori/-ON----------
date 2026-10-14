import json
import math


class BedrockEmbedder:
    def __init__(self, config):
        import boto3
        from botocore.config import Config
        self.config = config
        self.client = boto3.client("bedrock-runtime", region_name=config.region,
                                   config=Config(retries={"mode": "adaptive", "max_attempts": 8},
                                                 read_timeout=120, max_pool_connections=32))

    def embed(self, text):
        response = self.client.invoke_model(
            modelId=self.config.model, contentType="application/json", accept="application/json",
            body=json.dumps({"inputText": text, "dimensions": self.config.dimensions, "normalize": True}),
        )
        try:
            vector = json.loads(response["body"].read())["embedding"]
        finally:
            response["body"].close()
        validate_vector(vector, self.config.dimensions)
        return vector


def validate_vector(vector, dimensions):
    if len(vector) != dimensions or not all(isinstance(x, (float, int)) and math.isfinite(x) for x in vector):
        raise ValueError("임베딩 차원 또는 숫자 값이 잘못되었습니다.")
    if not any(vector):
        raise ValueError("0 벡터는 코사인 검색에 사용할 수 없습니다.")
