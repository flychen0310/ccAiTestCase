"""应用配置,统一从环境变量读取(启动时会自动加载 .env)。"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'app.db'}")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]

# 飞书开放平台(企业自建应用)凭证,用于从飞书文档链接抓取内容。
# 在飞书开放平台创建应用后填入,并给应用开通"查看、评论、编辑和管理云文档"相关权限。
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_BASE_URL = os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn")

# ---------- 需求配图(多模态)相关配置 ----------
# 需求可附带界面原型图/流程图/接口截图等,支持视觉能力的模型(openai/anthropic)会在
# "需求理解"阶段结合图片内容一起分析;不支持视觉的模型(deepseek/mock)会自动跳过图片、仅用文本。
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "data" / "uploads")))
# 单张图片大小上限(MB)
MAX_IMAGE_SIZE_MB = int(os.getenv("MAX_IMAGE_SIZE_MB", "8"))
# 单个需求最多附带的图片数量
MAX_IMAGES_PER_REQUIREMENT = int(os.getenv("MAX_IMAGES_PER_REQUIREMENT", "6"))
# 允许的图片 MIME 类型(与 openai/anthropic 视觉接口支持范围一致)
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
