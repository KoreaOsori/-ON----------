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
        vector, _ = await self.embed_with_usage(query)
        return vector

    async def embed_with_usage(self, query: str) -> tuple[list[float], dict]:
        def invoke():
            response = self.client.invoke_model(
                modelId=self.settings.embedding_model_id, contentType="application/json",
                accept="application/json", body=json.dumps({"inputText": query,
                    "dimensions": self.settings.embedding_dimensions, "normalize": True}))
            try:
                data = json.loads(response["body"].read())
                vector = data['embedding']
            finally:
                response["body"].close()
            if (len(vector) != self.settings.embedding_dimensions
                    or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector)
                    or not any(vector)):
                raise ValueError("Invalid embedding response")
            count = data.get('inputTextTokenCount')
            return vector, {'inputTokens': count, 'outputTokens': 0, 'totalTokens': count}
        return await asyncio.to_thread(invoke)

    async def generate(self, model_id: str, system: str, prompt: str, *, max_tokens: int | None = None) -> dict:
        # Sonnet 5.5 rejects "disabled". Match the configured ID so custom
        # inference profile ARNs for the Sonnet slot receive the same option.
        thinking_type = "between_tools" if model_id == self.settings.sonnet_model_id else "disabled"
        response = await asyncio.to_thread(
            self.client.converse, modelId=model_id, system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens or self.settings.max_output_tokens},
            additionalModelRequestFields={"thinking": {"type": thinking_type}})
        reason = response.get("stopReason")
        answer = "".join(block.get("text", "") for block in
                         response.get("output", {}).get("message", {}).get("content", []))
        return {"answer": answer, "stop_reason": reason, "usage": response.get("usage", {})}
