# 快速运行

完整环境、数据库初始化、安装启动命令和验收步骤见 [README.md](README.md#从安装到运行)。

顺序：配置真实 seekdb → 安装 `requirements-dev.txt` → `python setup_database.py` → `python import_samples.py` → `python -m uvicorn app:app --host 127.0.0.1 --port 8000`。

浏览器打开 `http://127.0.0.1:8000`。独立验收运行 `python verify.py`；通过状态以实际执行生成的 JSON 为准。
