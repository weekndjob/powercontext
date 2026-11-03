"""
研途 Research Desk - FastAPI 主应用
提供资料管理、全文检索、待办任务等功能
所有路由使用同步函数，避免在 async 中调用阻塞 IO
"""
import atexit
import json
import logging
import os
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from database import (
    get_db_connection, init_database_schema,
    check_connection, close_all_connections,
)
from models import (
    MaterialCreate, MaterialResponse, MaterialListResponse,
    SearchRequest, TodoCreate, TodoUpdate, TodoResponse,
    TodoListResponse, SummaryRequest, SummaryResponse, MessageResponse,
    TITLE_MAX_LENGTH, CONTENT_MAX_LENGTH, SOURCE_MAX_LENGTH,
    TAGS_MAX_LENGTH, TODO_TITLE_MAX_LENGTH, UPLOAD_MAX_BYTES,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="研途 Research Desk", version="1.0.0")

_BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))


def _safe_highlight_text(content: str, query: str, max_length: int = 150) -> str:
    """
    生成搜索高亮摘要。
    返回 (safe_html_prefix, [query_terms]) 形式，由前端 DOM 文本节点做高亮，
    避免 re.sub 模板注入和 HTML 实体二次转义问题。
    """
    if not content:
        return ""
    if not query or not query.strip():
        excerpt = content[:max_length]
        if len(content) > max_length:
            excerpt += "..."
        return excerpt

    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    if not terms:
        excerpt = content[:max_length]
        if len(content) > max_length:
            excerpt += "..."
        return excerpt

    first_term = terms[0]
    pattern = re.compile(re.escape(first_term), re.IGNORECASE)
    match = pattern.search(content)
    if match:
        start = max(0, match.start() - 50)
        end = min(len(content), match.end() + 100)
        excerpt = content[start:end]
        if start > 0:
            excerpt = "..." + excerpt
        if end < len(content):
            excerpt = excerpt + "..."
    else:
        excerpt = content[:max_length]
        if len(content) > max_length:
            excerpt += "..."
    return excerpt


def _normalize_tags_for_storage(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    parts = [t.strip() for t in raw.split(",") if t.strip()]
    seen = set()
    unique = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    if not unique:
        return None
    return ",".join(unique)


@app.on_event("startup")
def startup_event():
    if not check_connection():
        raise RuntimeError("数据库连接失败，请检查环境变量配置")
    try:
        init_database_schema()
    except Exception as e:
        logger.error(f"启动失败: {e}")
        raise


@app.on_event("shutdown")
def shutdown_event():
    close_all_connections()


atexit.register(close_all_connections)


def _render(request: Request, name: str):
    return templates.TemplateResponse(request=request, name=name)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return _render(request, "index.html")


@app.get("/materials", response_class=HTMLResponse)
def materials_page(request: Request):
    return _render(request, "materials.html")


@app.get("/search", response_class=HTMLResponse)
def search_page(request: Request):
    return _render(request, "search.html")


@app.get("/todos", response_class=HTMLResponse)
def todos_page(request: Request):
    return _render(request, "todos.html")


@app.get("/summary", response_class=HTMLResponse)
def summary_page(request: Request):
    return _render(request, "summary.html")


# ============ 资料 API ============

@app.post("/api/materials", response_model=MessageResponse)
def create_material(material: MaterialCreate):
    try:
        tags = _normalize_tags_for_storage(material.tags)
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                sql = "INSERT INTO materials (title, content, source, tags) VALUES (%s, %s, %s, %s)"
                cursor.execute(sql, (material.title.strip(), material.content, material.source, tags))
                material_id = cursor.lastrowid
        return MessageResponse(success=True, message="资料创建成功", data={"id": material_id})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建资料失败: {e}")
        raise HTTPException(status_code=500, detail="创建资料失败，请稍后重试")


@app.get("/api/materials", response_model=MaterialListResponse)
def list_materials(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    try:
        offset = (page - 1) * page_size
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) as total FROM materials")
                total = cursor.fetchone()["total"]
                sql = "SELECT id, title, content, source, tags, created_at FROM materials ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s"
                cursor.execute(sql, (page_size, offset))
                materials = cursor.fetchall()
        return MaterialListResponse(
            materials=[MaterialResponse(**m) for m in materials],
            total=total, page=page, page_size=page_size,
        )
    except Exception as e:
        logger.error(f"获取资料列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取资料列表失败")


@app.get("/api/materials/{material_id}", response_model=MaterialResponse)
def get_material(material_id: int):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id, title, content, source, tags, created_at FROM materials WHERE id = %s",
                    (material_id,),
                )
                material = cursor.fetchone()
        if not material:
            raise HTTPException(status_code=404, detail="资料不存在")
        return MaterialResponse(**material)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取资料详情失败: {e}")
        raise HTTPException(status_code=500, detail="获取资料详情失败")


@app.delete("/api/materials/{material_id}", response_model=MessageResponse)
def delete_material(material_id: int):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM materials WHERE id = %s FOR UPDATE", (material_id,))
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="资料不存在")
                cursor.execute("UPDATE todos SET material_id = NULL WHERE material_id = %s", (material_id,))
                cursor.execute("DELETE FROM materials WHERE id = %s", (material_id,))
        return MessageResponse(success=True, message="资料删除成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除资料失败: {e}")
        raise HTTPException(status_code=500, detail="删除资料失败")


# ============ 文本导入 API ============

@app.post("/api/materials/import", response_model=MessageResponse)
def import_text_file(
    title: str = Form(...),
    source: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    if not title or not title.strip():
        raise HTTPException(status_code=400, detail="标题不能为空")
    if len(title) > TITLE_MAX_LENGTH:
        raise HTTPException(status_code=400, detail=f"标题长度不能超过 {TITLE_MAX_LENGTH}")
    if not file.filename:
        raise HTTPException(status_code=400, detail="未选择文件")
    lower_name = file.filename.lower()
    if not (lower_name.endswith(".txt") or lower_name.endswith(".md")):
        raise HTTPException(status_code=400, detail="仅支持 .txt 或 .md 文件")

    try:
        raw = file.file.read(UPLOAD_MAX_BYTES + 1)
    except Exception:
        raise HTTPException(status_code=500, detail="读取文件失败")
    if len(raw) > UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=400, detail=f"文件大小超过上限 {UPLOAD_MAX_BYTES} 字节")

    for encoding in ("utf-8-sig", "utf-8"):
        try:
            content = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(status_code=400, detail="文件编码必须为 UTF-8")

    if not content.strip():
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > CONTENT_MAX_LENGTH:
        raise HTTPException(status_code=400, detail=f"文件内容超过 {CONTENT_MAX_LENGTH} 字符")

    try:
        material = MaterialCreate(title=title.strip(), content=content, source=source, tags=tags)
    except ValidationError:
        raise HTTPException(status_code=422, detail="导入资料字段不符合长度或格式要求")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                sql = "INSERT INTO materials (title, content, source, tags) VALUES (%s, %s, %s, %s)"
                cursor.execute(sql, (material.title, material.content, material.source, material.tags))
                material_id = cursor.lastrowid
        return MessageResponse(success=True, message="文件导入成功", data={"id": material_id})
    except Exception as e:
        logger.error(f"导入文件失败: {e}")
        raise HTTPException(status_code=500, detail="导入文件失败")


# ============ 检索 API ============

def _build_search_sql(search: SearchRequest):
    """构建检索 SQL 和参数，返回 (where_clause, where_params, has_ft, order_by)"""
    conditions = []
    where_params = []
    has_ft = False

    q = (search.query or "").strip()
    if q:
        conditions.append("MATCH(title, content) AGAINST(%s IN NATURAL LANGUAGE MODE)")
        where_params.append(q)
        has_ft = True

    if search.tags and search.tags.strip():
        for tag in search.tags.split(","):
            tag = tag.strip()
            if tag:
                conditions.append("FIND_IN_SET(%s, tags)")
                where_params.append(tag)

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    order_by = "relevance DESC, created_at DESC, id DESC" if has_ft else "created_at DESC, id DESC"
    return where_clause, where_params, has_ft, order_by


@app.post("/api/search", response_model=MaterialListResponse)
def search_materials(search: SearchRequest):
    try:
        where_clause, where_params, has_ft, order_by = _build_search_sql(search)
        offset = (search.page - 1) * search.page_size

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                count_sql = f"SELECT COUNT(*) as total FROM materials WHERE {where_clause}"
                cursor.execute(count_sql, list(where_params))
                total = cursor.fetchone()["total"]

                select_ft = ""
                select_params = []
                if has_ft:
                    select_ft = ", MATCH(title, content) AGAINST(%s IN NATURAL LANGUAGE MODE) as relevance"
                    select_params.append(search.query.strip())

                list_sql = f"""
                    SELECT id, title, LEFT(content, 200) as content, source, tags, created_at
                    {select_ft}
                    FROM materials
                    WHERE {where_clause}
                    ORDER BY {order_by}
                    LIMIT %s OFFSET %s
                """
                list_params = select_params + list(where_params) + [search.page_size, offset]
                cursor.execute(list_sql, list_params)
                materials = cursor.fetchall()

                for m in materials:
                    if has_ft and m.get("content"):
                        m["highlight"] = _safe_highlight_text(m["content"], search.query)
                    else:
                        m["highlight"] = None

        return MaterialListResponse(
            materials=[MaterialResponse(**m) for m in materials],
            total=total, page=search.page, page_size=search.page_size,
        )
    except Exception as e:
        logger.error(f"检索失败: {e}")
        raise HTTPException(status_code=500, detail="检索失败")


@app.get("/api/search", response_model=MaterialListResponse)
def search_materials_get(
    q: str = Query("", max_length=200),
    tags: Optional[str] = Query(None, max_length=500),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    search = SearchRequest(query=q, tags=tags, page=page, page_size=page_size)
    return search_materials(search)


# ============ 待办 API ============

@app.post("/api/todos", response_model=MessageResponse)
def create_todo(todo: TodoCreate):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                if todo.material_id is not None:
                    cursor.execute("SELECT id FROM materials WHERE id = %s FOR UPDATE", (todo.material_id,))
                    if not cursor.fetchone():
                        raise HTTPException(status_code=400, detail="关联的资料不存在")
                sql = "INSERT INTO todos (title, material_id, due_date) VALUES (%s, %s, %s)"
                cursor.execute(sql, (todo.title.strip(), todo.material_id, todo.due_date))
                todo_id = cursor.lastrowid
        return MessageResponse(success=True, message="待办创建成功", data={"id": todo_id})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建待办失败: {e}")
        raise HTTPException(status_code=500, detail="创建待办失败")


@app.get("/api/todos", response_model=TodoListResponse)
def list_todos(completed: Optional[bool] = None, material_id: Optional[int] = None):
    try:
        conditions = []
        params = []
        if completed is not None:
            conditions.append("t.completed = %s")
            params.append(1 if completed else 0)
        if material_id is not None:
            conditions.append("t.material_id = %s")
            params.append(material_id)
        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                sql = f"""
                    SELECT t.id, t.title, t.material_id, m.title as material_title,
                           t.due_date, t.completed, t.created_at, t.completed_at
                    FROM todos t
                    LEFT JOIN materials m ON t.material_id = m.id
                    WHERE {where_clause}
                    ORDER BY t.completed ASC, t.due_date ASC, t.created_at DESC, t.id DESC
                """
                cursor.execute(sql, params)
                todos = cursor.fetchall()
        return TodoListResponse(todos=[TodoResponse(**t) for t in todos], total=len(todos))
    except Exception as e:
        logger.error(f"获取待办列表失败: {e}")
        raise HTTPException(status_code=500, detail="获取待办列表失败")


@app.put("/api/todos/{todo_id}", response_model=MessageResponse)
def update_todo(todo_id: int, todo: TodoUpdate):
    try:
        updates = []
        params = []

        if todo.title is not None:
            updates.append("title = %s")
            params.append(todo.title.strip())
        if todo.clear_material_id or ("material_id" in todo.model_fields_set and todo.material_id is None):
            updates.append("material_id = NULL")
        elif todo.material_id is not None:
            updates.append("material_id = %s")
            params.append(todo.material_id)
        if todo.clear_due_date or ("due_date" in todo.model_fields_set and todo.due_date is None):
            updates.append("due_date = NULL")
        elif todo.due_date is not None:
            updates.append("due_date = %s")
            params.append(todo.due_date)
        if todo.completed is not None:
            # Evaluate the old status before assigning the new one, preserving
            # the completion timestamp when an idempotent update is repeated.
            updates.append("completed_at = CASE WHEN completed = %s THEN completed_at WHEN %s = 1 THEN CURRENT_TIMESTAMP ELSE NULL END")
            params.extend([1 if todo.completed else 0, 1 if todo.completed else 0])
            updates.append("completed = %s")
            params.append(1 if todo.completed else 0)

        if not updates:
            raise HTTPException(status_code=400, detail="没有要更新的字段")

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                if todo.material_id is not None and not todo.clear_material_id:
                    cursor.execute("SELECT id FROM materials WHERE id = %s FOR UPDATE", (todo.material_id,))
                    if not cursor.fetchone():
                        raise HTTPException(status_code=400, detail="关联的资料不存在")
                cursor.execute("SELECT id, completed FROM todos WHERE id = %s FOR UPDATE", (todo_id,))
                existing = cursor.fetchone()
                if not existing:
                    raise HTTPException(status_code=404, detail="待办不存在")

                sql = f"UPDATE todos SET {', '.join(updates)} WHERE id = %s"
                cursor.execute(sql, params + [todo_id])
        return MessageResponse(success=True, message="待办更新成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新待办失败: {e}")
        raise HTTPException(status_code=500, detail="更新待办失败")


@app.delete("/api/todos/{todo_id}", response_model=MessageResponse)
def delete_todo(todo_id: int):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM todos WHERE id = %s", (todo_id,))
                if cursor.rowcount == 0:
                    raise HTTPException(status_code=404, detail="待办不存在")
        return MessageResponse(success=True, message="待办删除成功")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除待办失败: {e}")
        raise HTTPException(status_code=500, detail="删除待办失败")


# ============ 汇总 API ============

@app.post("/api/summary", response_model=SummaryResponse)
def get_summary(request: SummaryRequest):
    try:
        if request.start_date and request.end_date and request.start_date > request.end_date:
            raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")

        date_conditions = []
        date_params = []
        if request.start_date:
            date_conditions.append("DATE(created_at) >= %s")
            date_params.append(request.start_date)
        if request.end_date:
            date_conditions.append("DATE(created_at) <= %s")
            date_params.append(request.end_date)
        date_where = " AND ".join(date_conditions) if date_conditions else "1=1"

        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) as count FROM materials WHERE {date_where}", date_params)
                total_materials = cursor.fetchone()["count"]

                cursor.execute(f"""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) as completed_count
                    FROM todos WHERE {date_where}
                """, date_params)
                todo_stats = cursor.fetchone()
                total_todos = todo_stats["total"]
                completed_todos = todo_stats["completed_count"] or 0
                pending_todos = total_todos - completed_todos
                completion_rate = (completed_todos / total_todos * 100) if total_todos > 0 else 0.0

                cursor.execute(f"""
                    SELECT DATE(created_at) as date, COUNT(*) as count
                    FROM materials WHERE {date_where}
                    GROUP BY DATE(created_at) ORDER BY date DESC
                """, date_params)
                materials_by_date = [dict(r) for r in cursor.fetchall()]

                cursor.execute(f"""
                    SELECT DATE(created_at) as date,
                           COUNT(*) as total,
                           SUM(CASE WHEN completed = 1 THEN 1 ELSE 0 END) as completed
                    FROM todos WHERE {date_where}
                    GROUP BY DATE(created_at) ORDER BY date DESC
                """, date_params)
                todos_by_date = [dict(r) for r in cursor.fetchall()]

        return SummaryResponse(
            start_date=request.start_date,
            end_date=request.end_date,
            total_materials=total_materials,
            total_todos=total_todos,
            completed_todos=completed_todos,
            pending_todos=pending_todos,
            completion_rate=completion_rate,
            materials_by_date=materials_by_date,
            todos_by_date=todos_by_date,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取汇总失败: {e}")
        raise HTTPException(status_code=500, detail="获取汇总失败")


@app.get("/api/health")
def health_check():
    ok = check_connection()
    if ok:
        return {"status": "healthy", "database": "connected"}
    return JSONResponse(
        status_code=503,
        content={"status": "unhealthy", "database": "disconnected"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("APP_HOST", "127.0.0.1"), port=int(os.environ.get("APP_PORT", "8000")))
