"""加载 prompts/*.jinja2 模板文件,拆分出 system/schema/few_shot/user 四个区块,
分别用 Jinja2 渲染变量,再拼装成最终发给 LLM 的 system message 和 user message。

模板文件里用 `{% block name %}...{% endblock %}` 只是作为区块分隔标记,
这里用正则提取区块内容后独立渲染,不使用 Jinja2 的模板继承机制。
"""
import re
from pathlib import Path
from typing import Any, Dict, Tuple

from jinja2 import Environment

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

_BLOCK_RE = re.compile(r"{%\s*block\s+(\w+)\s*%}(.*?){%\s*endblock\s*%}", re.DOTALL)

_env = Environment(trim_blocks=True, lstrip_blocks=True)


def _extract_blocks(raw_template: str) -> Dict[str, str]:
    blocks = {}
    for name, content in _BLOCK_RE.findall(raw_template):
        blocks[name] = content.strip()
    return blocks


def load_prompt(template_name: str, variables: Dict[str, Any]) -> Tuple[str, str]:
    """加载并渲染 prompt 模板。

    Args:
        template_name: prompts/ 目录下的文件名,例如 "requirement_analysis.jinja2"
        variables: 用于渲染 user/few_shot 区块的变量

    Returns:
        (system_message, user_message)
    """
    path = PROMPTS_DIR / template_name
    raw = path.read_text(encoding="utf-8")
    blocks = _extract_blocks(raw)

    system_parts = [_env.from_string(blocks["system"]).render(**variables)]
    if "schema" in blocks:
        system_parts.append("### 输出格式(JSON Schema)\n" + blocks["schema"].strip())
    if "few_shot" in blocks:
        system_parts.append(_env.from_string(blocks["few_shot"]).render(**variables))

    system_message = "\n\n".join(system_parts)
    user_message = _env.from_string(blocks["user"]).render(**variables)
    return system_message, user_message
