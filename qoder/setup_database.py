"""Create only the configured project database and its tables."""
import re

import pymysql

from database import DatabaseConfig, init_database_schema


def main():
    config = DatabaseConfig()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", config.database):
        raise ValueError("Database name must contain 1–64 ASCII letters, digits or underscores")
    params = config.get_connection_params()
    params.pop("database")
    connection = pymysql.connect(**params)
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{config.database}` CHARACTER SET utf8mb4")
        connection.commit()
    finally:
        connection.close()
    init_database_schema()
    print("Project database and tables are ready")


if __name__ == "__main__":
    main()
