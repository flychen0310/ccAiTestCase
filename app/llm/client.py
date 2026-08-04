"""统一 LLM 调用客户端。

通过环境变量 LLM_PROVIDER 切换供应商:
  - "openai":    使用 OPENAI_API_KEY,默认模型 gpt-4o-mini
  - "anthropic": 使用 ANTHROPIC_API_KEY,默认模型 claude-3-5-sonnet-20241022
  - "deepseek":  使用 DEEPSEEK_API_KEY,默认模型 deepseek-chat(接口与 OpenAI 兼容)
  - "mock":      不发起真实请求,返回调用方传入的 mock_response,用于无 API key 时验证逻辑
"""
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class LLMResult:
    content: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    model: str
    extra: Dict = field(default_factory=dict)


def extract_json(text: str):
    """从模型输出中提取 JSON。兼容模型偶尔仍会用 ```json 包裹的情况。"""
    text = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    return json.loads(text)


class LLMClient:
    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "mock")).lower()
        default_models = {
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-5-sonnet-20241022",
            "deepseek": "deepseek-chat",
            "mock": "mock-model",
        }
        self.model = model or os.getenv("LLM_MODEL", default_models.get(self.provider, "mock-model"))

    def chat(self, system: str, user: str, temperature: float = 0.2, mock_response: str = "") -> LLMResult:
        start = time.time()
        if self.provider == "openai":
            result = self._chat_openai(system, user, temperature)
        elif self.provider == "anthropic":
            result = self._chat_anthropic(system, user, temperature)
        elif self.provider == "deepseek":
            result = self._chat_deepseek(system, user, temperature)
        elif self.provider == "mock":
            result = self._chat_mock(mock_response)
        else:
            raise ValueError(f"不支持的 LLM_PROVIDER: {self.provider}")
        result.latency_ms = (time.time() - start) * 1000
        result.model = self.model
        return result

    def _chat_openai(self, system: str, user: str, temperature: float) -> LLMResult:
        from openai import OpenAI

        client = OpenAI(timeout=90.0, max_retries=2)
        resp = client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        usage = resp.usage
        return LLMResult(
            content=resp.choices[0].message.content,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            latency_ms=0.0,
            model=self.model,
        )

    def _chat_anthropic(self, system: str, user: str, temperature: float) -> LLMResult:
        import anthropic

        client = anthropic.Anthropic(timeout=90.0, max_retries=2)
        resp = client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
        return LLMResult(
            content=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            latency_ms=0.0,
            model=self.model,
        )

    def _chat_deepseek(self, system: str, user: str, temperature: float) -> LLMResult:
        from openai import OpenAI

        client = OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url="https://api.deepseek.com",
            timeout=90.0,
            max_retries=2,
        )
        resp = client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        usage = resp.usage
        return LLMResult(
            content=resp.choices[0].message.content,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            latency_ms=0.0,
            model=self.model,
        )

    def _chat_mock(self, mock_response: str) -> LLMResult:
        return LLMResult(
            content=mock_response,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0.0,
            model=self.model,
            extra={"mock": True},
        )
