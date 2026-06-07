"""店长经营工作台 V0.1.2 独立子包。

与 V0.1.1 诊断主链路、现有 SQLAlchemy 主库完全隔离：
- 路由前缀 /api/store-manager
- 存储为独立 SQLite 文件（STORE_MANAGER_DB_PATH），不进主库
- 引擎为规则 + 模板，不依赖大模型
"""


def model_to_dict(model):
    """兼容 pydantic v1 (.dict()) 与 v2 (.model_dump())。"""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()
