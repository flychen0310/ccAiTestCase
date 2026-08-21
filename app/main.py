from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from app.config import CORS_ORIGINS
from app.database import init_db
from app.routers import cases, knowledge, requirements

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# 前端静态资源易被浏览器缓存，导致改动后看不到最新代码，这里统一禁用缓存
NO_CACHE_HEADER = "no-cache, no-store, must-revalidate"


class NoCacheStaticFiles(StaticFiles):
    """返回静态文件时附带禁用缓存的响应头，强制浏览器每次重新校验。"""

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = NO_CACHE_HEADER
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AI 辅助测试用例生成平台",
    description="需求录入 -> AI 需求理解 -> AI 分类型用例生成 -> 人工审核 -> 导出",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(requirements.router)
app.include_router(cases.router)
app.include_router(knowledge.router)

app.mount("/static", NoCacheStaticFiles(directory=WEB_DIR), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/")
def index():
    return FileResponse(
        WEB_DIR / "index.html",
        headers={"Cache-Control": NO_CACHE_HEADER},
    )
