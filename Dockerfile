# AI 辅助测试用例生成平台 - 生产镜像
FROM python:3.11-slim

# 避免生成 pyc、日志实时刷出
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先装依赖，利用 Docker 层缓存(依赖没变时不重复安装)
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 再拷贝应用代码
COPY app ./app
COPY web ./web
COPY prompts ./prompts

# 数据目录(SQLite 库文件 + 上传的配图),运行时通过 volume 挂载做持久化
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

# 生产用单进程多协程即可(LLM 调用是 IO 密集)。
# 如需多 worker,请先把 DATABASE_URL 切到 PostgreSQL,否则 SQLite 多进程写会锁库。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
