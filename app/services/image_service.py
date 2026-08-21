"""需求配图的落盘、读取、删除,以及转换成 LLM 多模态输入。

图片文件存放在 config.UPLOAD_DIR/{requirement_id}/ 下,数据库只记录相对路径与元信息。
需求理解阶段调用 load_llm_images 把图片读成 base64,喂给支持视觉的模型。
"""
import base64
import uuid
from pathlib import Path
from typing import List

from sqlalchemy.orm import Session

from app import config, models
from app.config import BASE_DIR
from app.llm.client import ImageData

_EXT_BY_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class ImageUploadError(Exception):
    """图片上传校验失败(类型不支持、超大、数量超限等),路由层据此返回明确提示。"""


def _requirement_dir(requirement_id: int) -> Path:
    d = config.UPLOAD_DIR / str(requirement_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def abs_path(image: models.RequirementImage) -> Path:
    """把库里存的相对路径还原成磁盘绝对路径。"""
    return BASE_DIR / image.stored_path


def save_uploads(
    db: Session,
    requirement: models.Requirement,
    uploads: List[tuple[str, str, bytes]],
) -> List[models.RequirementImage]:
    """保存一批上传的图片。

    uploads: [(filename, content_type, data_bytes), ...]
    """
    existing = len(requirement.images)
    if existing + len(uploads) > config.MAX_IMAGES_PER_REQUIREMENT:
        raise ImageUploadError(
            f"单个需求最多附带 {config.MAX_IMAGES_PER_REQUIREMENT} 张图片"
            f"(当前已有 {existing} 张,本次尝试新增 {len(uploads)} 张)。"
        )

    max_bytes = config.MAX_IMAGE_SIZE_MB * 1024 * 1024
    saved: List[models.RequirementImage] = []
    target_dir = _requirement_dir(requirement.id)

    for filename, content_type, data in uploads:
        content_type = (content_type or "").lower()
        if content_type not in config.ALLOWED_IMAGE_TYPES:
            raise ImageUploadError(
                f"图片「{filename}」类型不支持({content_type or '未知'})。"
                f"仅支持 {', '.join(sorted(config.ALLOWED_IMAGE_TYPES))}。"
            )
        if len(data) > max_bytes:
            raise ImageUploadError(
                f"图片「{filename}」大小 {len(data) / 1024 / 1024:.1f}MB,超过上限 {config.MAX_IMAGE_SIZE_MB}MB。"
            )

        ext = _EXT_BY_TYPE.get(content_type, "")
        disk_name = f"{uuid.uuid4().hex}{ext}"
        disk_path = target_dir / disk_name
        disk_path.write_bytes(data)

        record = models.RequirementImage(
            requirement_id=requirement.id,
            filename=filename or disk_name,
            stored_path=str(disk_path.relative_to(BASE_DIR)),
            content_type=content_type,
            size_bytes=len(data),
        )
        db.add(record)
        saved.append(record)

    db.commit()
    for record in saved:
        db.refresh(record)
    return saved


def delete_image(db: Session, image: models.RequirementImage) -> None:
    path = abs_path(image)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass  # 文件删不掉不阻塞数据库记录删除
    db.delete(image)
    db.commit()


def load_llm_images(requirement: models.Requirement) -> List[ImageData]:
    """把需求的配图读成 LLM 可用的 base64 输入。读不到的文件跳过。"""
    images: List[ImageData] = []
    for img in requirement.images:
        path = abs_path(img)
        if not path.exists():
            continue
        data_b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        images.append(ImageData(media_type=img.content_type, data_b64=data_b64))
    return images
