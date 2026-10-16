import asyncio
import json
import math
from functools import cached_property

from .aws_auth import client_config, session_for
from .config import Settings


class Bedrock:
    def __init__(self, settings: Settings):
        self.settings = settings

    @cached_property
    def client(self):
        return session_for(self.settings).client("bedrock-runtime", config=client_config())

    async def embed(self, query: str) -> list[float]:
        def invoke():
            response = self.client.invoke_model(
                modelId=self.settings.embedding_model_id, contentType="application/json",
                accept="application/json", body=json.dumps({"inputText": query,
                    "dimensions": self.settings.embedding_dimensions, "normalize": True}))
            try:
                vector = json.loads(response["body"].read())["embedding"]
            finally:
                response["body"].close()
            if (len(vector) != self.settings.embedding_dimensions
                    or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector)
                    or not any(vector)):
                raise ValueError("Invalid embedding response")
            return vector
        return await asyncio.to_thread(invoke)

    async def generate(self, model_id: str, system: str, prompt: str) -> dict:
        response = await asyncio.to_thread(
            self.client.converse, modelId=model_id, system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": self.settings.max_output_tokens},
            additionalModelRequestFields={"thinking": {"type": "disabled"}})
        reason = response.get("stopReason")
        answer = "".join(block.get("text", "") for block in
                         response.get("output", {}).get("message", {}).get("content", []))
        return {"answer": answer, "stop_reason": reason, "usage": response.get("usage", {})}
