"""
Pydantic 模型定义
用于请求和响应的数据验证
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime, date


TITLE_MAX_LENGTH = 500
CONTENT_MAX_LENGTH = 50000
SOURCE_MAX_LENGTH = 1000
TAGS_MAX_LENGTH = 500
TODO_TITLE_MAX_LENGTH = 500
UPLOAD_MAX_BYTES = 2 * 1024 * 1024  # 2MB


def _reject_blank(v: str, name: str) -> str:
    if not v.strip():
        raise ValueError(f"{name}不能为纯空白")
    return v


class MaterialCreate(BaseModel):
    """创建资料的请求模型"""
    title: str = Field(..., min_length=1, max_length=TITLE_MAX_LENGTH)
    content: str = Field(..., min_length=1, max_length=CONTENT_MAX_LENGTH)
    source: Optional[str] = Field(None, max_length=SOURCE_MAX_LENGTH)
    tags: Optional[str] = Field(None, max_length=TAGS_MAX_LENGTH)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        return _reject_blank(v, "标题")

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        return _reject_blank(v, "正文")

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        parts = [t.strip() for t in v.split(",") if t.strip()]
        seen = set()
        unique = []
        for p in parts:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        if not unique:
            return None
        result = ",".join(unique)
        if len(result) > TAGS_MAX_LENGTH:
            raise ValueError(f"标签总长度不能超过 {TAGS_MAX_LENGTH} 字符")
        return result


class MaterialResponse(BaseModel):
    """资料响应模型"""
    id: int
    title: str
    content: str
    source: Optional[str]
    tags: Optional[str]
    created_at: datetime
    relevance: Optional[float] = None
    highlight: Optional[str] = None


class MaterialListResponse(BaseModel):
    """资料列表响应"""
    materials: List[MaterialResponse]
    total: int
    page: int
    page_size: int


class SearchRequest(BaseModel):
    """搜索请求模型"""
    query: str = Field("", max_length=200)
    tags: Optional[str] = Field(None, max_length=TAGS_MAX_LENGTH)
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        parts = [t.strip() for t in v.split(",") if t.strip()]
        if not parts:
            return None
        return ",".join(parts)


class TodoCreate(BaseModel):
    """创建待办的请求模型"""
    title: str = Field(..., min_length=1, max_length=TODO_TITLE_MAX_LENGTH)
    material_id: Optional[int] = Field(None, ge=1)
    due_date: Optional[date] = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: str) -> str:
        return _reject_blank(v, "标题")


class TodoUpdate(BaseModel):
    """更新待办的请求模型"""
    title: Optional[str] = Field(None, min_length=1, max_length=TODO_TITLE_MAX_LENGTH)
    material_id: Optional[int] = Field(None, ge=1)
    due_date: Optional[date] = None
    completed: Optional[bool] = None
    clear_material_id: Optional[bool] = None
    clear_due_date: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return _reject_blank(v, "标题")


class TodoResponse(BaseModel):
    """待办响应模型"""
    id: int
    title: str
    material_id: Optional[int]
    material_title: Optional[str] = None
    due_date: Optional[date]
    completed: bool
    created_at: datetime
    completed_at: Optional[datetime]


class TodoListResponse(BaseModel):
    """待办列表响应"""
    todos: List[TodoResponse]
    total: int


class SummaryRequest(BaseModel):
    """汇总请求模型"""
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class SummaryResponse(BaseModel):
    """汇总响应模型"""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    total_materials: int
    total_todos: int
    completed_todos: int
    pending_todos: int
    completion_rate: float
    materials_by_date: List[dict]
    todos_by_date: List[dict]


class MessageResponse(BaseModel):
    """通用消息响应"""
    success: bool
    message: str
    data: Optional[dict] = None
