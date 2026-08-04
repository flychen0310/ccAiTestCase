"""SQLAlchemy 引擎与会话管理。

默认使用 SQLite(免安装,适合本地开发/演示),生产环境可通过 DATABASE_URL
环境变量切换到 PostgreSQL,例如:
  DATABASE_URL=postgresql+psycopg2://user:pwd@host:5432/dbname
"""
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL

if DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.split("///")[-1]
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from app import models  # noqa: F401 确保模型被注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
