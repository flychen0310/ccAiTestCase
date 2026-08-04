"""SQLAlchemy 引擎与会话管理。

默认使用 SQLite(免安装,适合本地开发/演示),生产环境可通过 DATABASE_URL
环境变量切换到 PostgreSQL,例如:
  DATABASE_URL=postgresql+psycopg2://user:pwd@host:5432/dbname
"""
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
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


def _sync_missing_columns() -> None:
    """轻量级"迁移":没有引入 Alembic,create_all 只会建新表,不会给已存在的表加新列。
    这里给已存在表补上模型里新增的列(仅适用于新增可空列这种简单场景)。
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.tables.values():
            if table.name not in existing_tables:
                continue
            existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                col_type = column.type.compile(engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))


def init_db() -> None:
    from app import models  # noqa: F401 确保模型被注册到 Base.metadata

    Base.metadata.create_all(bind=engine)
    _sync_missing_columns()
