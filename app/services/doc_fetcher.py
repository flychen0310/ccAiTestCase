"""从外部文档链接抓取纯文本,供需求录入使用。

当前实现飞书文档(docx / 旧版 docs / wiki 节点)。设计成可扩展的分发结构,
以后接入 TAPD、普通网页时新增对应的 fetch 函数并在 fetch_from_url 里分发即可。

飞书后端直连开放平台 API(需要企业自建应用的 app_id/app_secret):
  1. app_id + app_secret 换 tenant_access_token
  2. wiki 链接先把 wiki token 换成实际文档的 obj_token
  3. docx 文档调 raw_content 拿纯文本,调 document meta 拿标题
"""
import re
import threading
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import httpx

from app import config

# 抓取正文的长度上限:飞书文档可能很长,整篇塞给后续 LLM 会超上下文/推高成本,
# 这里做个保护性截断,超出部分丢弃并给出提示。
MAX_CONTENT_CHARS = 20000


class DocFetchError(Exception):
    """抓取失败(凭证缺失、链接不支持、飞书接口报错等),路由层据此返回明确提示。"""


@dataclass
class FetchedDoc:
    title: str
    content: str
    source: str  # feishu / tapd / web
    source_ref_id: Optional[str]  # 文档 id / story id 等,便于回溯来源


# ---------- 飞书 token 缓存(tenant_access_token 有效期约 2 小时)----------
# 同步路由会被 FastAPI 放到线程池并发执行,这里用锁保护缓存读写,避免并发换 token。
_token_cache = {"token": "", "expire_at": 0.0}
_token_lock = threading.Lock()

# 复用连接池,避免每次抓取都重新建连/握手(一次导入涉及多个串行请求)。
_http_client = httpx.Client(timeout=30)


def _get_feishu_token() -> str:
    if not config.FEISHU_APP_ID or not config.FEISHU_APP_SECRET:
        raise DocFetchError(
            "未配置飞书应用凭证。请在 .env 里填写 FEISHU_APP_ID 和 FEISHU_APP_SECRET "
            "(在飞书开放平台创建企业自建应用后获取,并开通云文档读取权限)。"
        )

    with _token_lock:
        now = time.time()
        if _token_cache["token"] and now < _token_cache["expire_at"]:
            return _token_cache["token"]

        url = f"{config.FEISHU_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal"
        try:
            resp = _http_client.post(
                url,
                json={"app_id": config.FEISHU_APP_ID, "app_secret": config.FEISHU_APP_SECRET},
                timeout=15,
            )
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            raise DocFetchError(f"请求飞书 token 接口失败: {e}") from e

        if data.get("code") != 0:
            raise DocFetchError(f"获取飞书 token 失败: {data.get('msg')} (code={data.get('code')})")

        token = data["tenant_access_token"]
        _token_cache["token"] = token
        _token_cache["expire_at"] = now + int(data.get("expire", 7200)) - 120  # 提前 2 分钟过期
        return token


def _feishu_get(path: str, token: str, params: Optional[dict] = None) -> dict:
    url = f"{config.FEISHU_BASE_URL}{path}"
    try:
        resp = _http_client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        raise DocFetchError(f"请求飞书接口失败({path}): {e}") from e
    if data.get("code") != 0:
        raise DocFetchError(f"飞书接口返回错误({path}): {data.get('msg')} (code={data.get('code')})")
    return data.get("data", {})


def _parse_feishu_link(url: str) -> tuple[str, str]:
    """从飞书链接解析出 (类型, token)。类型: docx / docs / wiki。

    典型链接:
      https://xxx.feishu.cn/docx/<token>
      https://xxx.feishu.cn/docs/<token>
      https://xxx.feishu.cn/wiki/<token>
    """
    path = urlparse(url).path
    m = re.search(r"/(docx|docs|wiki)/([A-Za-z0-9]+)", path)
    if not m:
        raise DocFetchError(
            "无法从链接中识别飞书文档 id。支持的链接形如 https://xxx.feishu.cn/docx/xxxxx"
        )
    return m.group(1), m.group(2)


def _resolve_wiki_to_docx(wiki_token: str, token: str) -> str:
    """wiki 节点 token 换成底层实际文档的 obj_token(通常是 docx)。"""
    data = _feishu_get("/open-apis/wiki/v2/spaces/get_node", token, params={"token": wiki_token})
    node = data.get("node", {})
    obj_type = node.get("obj_type")
    if obj_type != "docx":
        raise DocFetchError(f"该 wiki 节点类型为 {obj_type},暂只支持 docx 文档")
    return node["obj_token"]


def fetch_feishu(url: str) -> FetchedDoc:
    token = _get_feishu_token()
    doc_type, doc_token = _parse_feishu_link(url)

    if doc_type == "wiki":
        document_id = _resolve_wiki_to_docx(doc_token, token)
    elif doc_type == "docx":
        document_id = doc_token
    else:  # 旧版 docs 不走 docx raw_content 接口
        raise DocFetchError(
            "该链接是飞书旧版文档(/docs/),当前仅支持新版文档(/docx/)和 wiki 节点。"
            "可在飞书里将文档另存为新版文档后重试。"
        )

    raw = _feishu_get(f"/open-apis/docx/v1/documents/{document_id}/raw_content", token)
    content = (raw.get("content") or "").strip()
    if not content:
        raise DocFetchError("飞书文档内容为空,或应用没有该文档的读取权限。")

    if len(content) > MAX_CONTENT_CHARS:
        content = content[:MAX_CONTENT_CHARS].rstrip() + f"\n\n…(正文超过 {MAX_CONTENT_CHARS} 字,已截断,请按需精简后再生成用例)"

    # 正文已到手,标题只是锦上添花:meta 请求失败时降级用正文首行,不让整次抓取白费。
    title = ""
    try:
        meta = _feishu_get(f"/open-apis/docx/v1/documents/{document_id}", token)
        title = meta.get("document", {}).get("title") or ""
    except DocFetchError:
        title = ""
    if not title:
        title = content.splitlines()[0][:80]

    return FetchedDoc(title=title, content=content, source="feishu", source_ref_id=document_id)


def fetch_from_url(url: str) -> FetchedDoc:
    url = url.strip()
    host = urlparse(url).netloc.lower()
    if not host:
        raise DocFetchError("请输入合法的链接地址。")

    if "feishu.cn" in host or "larksuite.com" in host or "larkoffice.com" in host:
        return fetch_feishu(url)

    raise DocFetchError(f"暂不支持该来源的链接: {host}。当前仅支持飞书文档。")
