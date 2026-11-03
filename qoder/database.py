"""
数据库配置和连接管理模块
从环境变量读取 seekdb 连接配置
每个连接上下文独立连接、提交或回滚，然后关闭连接
"""
import os
import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
WRITE_TIMEOUT = 30


class DatabaseConfig:
    """数据库配置，从环境变量读取"""

    def __init__(self):
        self.host = os.getenv("SEEKDB_HOST", "127.0.0.1")
        self.port = int(os.getenv("SEEKDB_PORT", "2881"))
        self.user = os.getenv("SEEKDB_USER", "root")
        self.password = os.getenv("SEEKDB_PASSWORD", "")
        self.database = os.getenv("SEEKDB_DATABASE", "qoder_research_desk")
        self.charset = "utf8mb4"

    def get_connection_params(self) -> dict:
        """获取连接参数"""
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "charset": self.charset,
            "cursorclass": DictCursor,
            "autocommit": False,
            "connect_timeout": CONNECT_TIMEOUT,
            "read_timeout": READ_TIMEOUT,
            "write_timeout": WRITE_TIMEOUT,
        }


_config = None


def get_config() -> DatabaseConfig:
    """获取数据库配置（单例）"""
    global _config
    if _config is None:
        _config = DatabaseConfig()
    return _config


@contextmanager
def get_db_connection():
    """获取数据库连接的上下文管理器，每次创建新连接，用后关闭"""
    config = get_config()
    conn = pymysql.connect(**config.get_connection_params())
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def init_database_schema():
    """
    初始化数据库表结构
    幂等操作：如果表已存在则跳过
    使用 seekdb 兼容语法：ik 分词器，无 ENGINE/外键/CREATE INDEX IF NOT EXISTS
    """
    materials_sql = """
    CREATE TABLE IF NOT EXISTS materials (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(500) NOT NULL,
        content MEDIUMTEXT NOT NULL,
        source VARCHAR(1000),
        tags VARCHAR(500),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_materials_tags (tags),
        INDEX idx_materials_created (created_at),
        FULLTEXT INDEX ft_idx_content (title, content) WITH PARSER ik
    )
    """

    todos_sql = """
    CREATE TABLE IF NOT EXISTS todos (
        id INT AUTO_INCREMENT PRIMARY KEY,
        title VARCHAR(500) NOT NULL,
        material_id INT,
        due_date DATE,
        completed TINYINT(1) DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP NULL,
        INDEX idx_todos_material_id (material_id),
        INDEX idx_todos_completed (completed),
        INDEX idx_todos_due_date (due_date),
        INDEX idx_todos_created (created_at)
    )
    """

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(materials_sql)
                cursor.execute("SHOW COLUMNS FROM materials LIKE 'content'")
                content_column = cursor.fetchone()
                if content_column["Type"].lower() == "text":
                    # Earlier schemas used a 64 KiB TEXT column, insufficient
                    # for 50,000 Unicode characters. Preserve existing rows.
                    cursor.execute("ALTER TABLE materials MODIFY COLUMN content MEDIUMTEXT NOT NULL")
                cursor.execute(todos_sql)
        logger.info("数据库表结构初始化成功")
        return True
    except Exception as e:
        logger.error(f"数据库表结构初始化失败: {e}")
        raise


def check_connection() -> bool:
    """检查数据库连接是否正常"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"数据库连接检查失败: {e}")
        return False


def close_all_connections():
    """关闭所有连接（当前实现为无操作，因为每次请求都创建新连接）"""
    pass
