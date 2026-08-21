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
from typing import Dict, List, Optional

# 支持视觉(图片输入)的供应商。deepseek 官方 API 与 mock 均为纯文本,不在此列。
VISION_PROVIDERS = {"openai", "anthropic"}


@dataclass
class ImageData:
    """一张待发送给多模态模型的图片。"""

    media_type: str  # image/png, image/jpeg, image/webp, image/gif
    data_b64: str  # base64 编码后的图片内容(不含 data: 前缀)


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

    def supports_vision(self) -> bool:
        """当前供应商是否支持图片输入。调用方据此决定是否把配图传进来。"""
        return self.provider in VISION_PROVIDERS

    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        mock_response: str = "",
        images: Optional[List[ImageData]] = None,
    ) -> LLMResult:
        # 不支持视觉的供应商直接忽略图片,退化为纯文本,保证流程不因图片而失败。
        if images and not self.supports_vision():
            images = None
        start = time.time()
        if self.provider == "openai":
            result = self._chat_openai(system, user, temperature, images)
        elif self.provider == "anthropic":
            result = self._chat_anthropic(system, user, temperature, images)
        elif self.provider == "deepseek":
            result = self._chat_deepseek(system, user, temperature)
        elif self.provider == "mock":
            result = self._chat_mock(mock_response)
        else:
            raise ValueError(f"不支持的 LLM_PROVIDER: {self.provider}")
        result.latency_ms = (time.time() - start) * 1000
        result.model = self.model
        return result

    def _chat_openai_compatible(
        self, client, system: str, user: str, temperature: float, images: Optional[List[ImageData]] = None
    ) -> LLMResult:
        """OpenAI 及其兼容接口(如 DeepSeek)共用的对话逻辑,仅 client 初始化不同。"""
        if images:
            user_content = [{"type": "text", "text": user}]
            for img in images:
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{img.media_type};base64,{img.data_b64}"},
                    }
                )
        else:
            user_content = user
        resp = client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
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

    def _chat_openai(
        self, system: str, user: str, temperature: float, images: Optional[List[ImageData]] = None
    ) -> LLMResult:
        from openai import OpenAI

        client = OpenAI(timeout=90.0, max_retries=2)
        return self._chat_openai_compatible(client, system, user, temperature, images)

    def _chat_anthropic(
        self, system: str, user: str, temperature: float, images: Optional[List[ImageData]] = None
    ) -> LLMResult:
        import anthropic

        client = anthropic.Anthropic(timeout=90.0, max_retries=2)
        content: list = [{"type": "text", "text": user}]
        for img in images or []:
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": img.media_type, "data": img.data_b64},
                }
            )
        resp = client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": content}],
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
        return self._chat_openai_compatible(client, system, user, temperature)

    def _chat_mock(self, mock_response: str) -> LLMResult:
        return LLMResult(
            content=mock_response,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0.0,
            model=self.model,
            extra={"mock": True},
        )
