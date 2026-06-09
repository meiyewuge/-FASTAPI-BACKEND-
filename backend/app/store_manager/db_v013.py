"""V0.1.3 店长工作台 · 独立 SQLite 数据底座（14 张表 + 索引）。

设计原则（遵守总审补丁说明 V0.1 红线）：
- 独立 SQLite 文件，与主库（SQLAlchemy）完全隔离，不动生产库、不做迁移。
- 新表独立，与 V0.1.2 的 store_manager_reports / store_manager_tasks 并存于同一独立库。
- 表结构 1:1 落地《后端开发文档》第 2 节 + 补丁5 高频索引。
"""
import os
import sqlite3

# 与 V0.1.2 复用同一独立测试库（不进主库）。可用环境变量覆盖。
DB_PATH = os.getenv("STORE_MANAGER_DB_PATH", "/opt/meiye-wuyou/data/store_manager_workbench.db")

# api_version 仅用于内部日志/调试（补丁4：前缀不变，不启 /api/v2）。
API_VERSION = "v0.1.3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS store_daily_raw_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL DEFAULT 'default_store',
    report_date TEXT NOT NULL,
    daily_revenue DECIMAL(12,2) NOT NULL DEFAULT 0,
    daily_recharge_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
    daily_product_retail DECIMAL(12,2) NOT NULL DEFAULT 0,
    daily_visits INTEGER NOT NULL DEFAULT 0,
    daily_new_customers INTEGER NOT NULL DEFAULT 0,
    daily_valid_appointments INTEGER NOT NULL DEFAULT 0,
    daily_appointment_arrivals INTEGER NOT NULL DEFAULT 0,
    daily_transaction_customers INTEGER NOT NULL DEFAULT 0,
    daily_transaction_orders INTEGER NOT NULL DEFAULT 0,
    daily_new_transaction INTEGER NOT NULL DEFAULT 0,
    daily_project_sales DECIMAL(12,2) NOT NULL DEFAULT 0,
    daily_main_project_sales DECIMAL(12,2) NOT NULL DEFAULT 0,
    daily_service_count INTEGER NOT NULL DEFAULT 0,
    daily_staff_count INTEGER NOT NULL DEFAULT 0,
    daily_complaints INTEGER NOT NULL DEFAULT 0,
    daily_notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(store_id, report_date)
);
CREATE INDEX IF NOT EXISTS idx_raw_data_date ON store_daily_raw_data(report_date);
CREATE INDEX IF NOT EXISTS idx_raw_data_store ON store_daily_raw_data(store_id);

CREATE TABLE IF NOT EXISTS store_computed_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL DEFAULT 'default_store',
    report_date TEXT NOT NULL,
    raw_data_id INTEGER NOT NULL,
    conversion_rate DECIMAL(5,2) NOT NULL DEFAULT 0,
    new_customer_ratio DECIMAL(5,2) NOT NULL DEFAULT 0,
    new_conversion_rate DECIMAL(5,2) NOT NULL DEFAULT 0,
    avg_order_value DECIMAL(12,2) NOT NULL DEFAULT 0,
    appointment_arrival_rate DECIMAL(5,2) NOT NULL DEFAULT 0,
    per_capita_efficiency DECIMAL(12,2) NOT NULL DEFAULT 0,
    recharge_ratio DECIMAL(5,2) NOT NULL DEFAULT 0,
    project_ratio DECIMAL(5,2) NOT NULL DEFAULT 0,
    product_ratio DECIMAL(5,2) NOT NULL DEFAULT 0,
    main_project_ratio DECIMAL(5,2) NOT NULL DEFAULT 0,
    complaint_risk_index DECIMAL(8,2) NOT NULL DEFAULT 0,
    estimated_return_customers INTEGER NOT NULL DEFAULT 0,
    service_efficiency DECIMAL(8,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (raw_data_id) REFERENCES store_daily_raw_data(id),
    UNIQUE(store_id, report_date)
);
CREATE INDEX IF NOT EXISTS idx_metrics_date ON store_computed_metrics(report_date);

CREATE TABLE IF NOT EXISTS store_diagnosis_result (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL DEFAULT 'default_store',
    report_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    data_overview TEXT DEFAULT '{}',
    computed_metrics TEXT DEFAULT '{}',
    top_issues TEXT DEFAULT '[]',
    customer_opportunities TEXT DEFAULT '{}',
    tomorrow_actions TEXT DEFAULT '[]',
    raw_data_id INTEGER,
    metrics_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (raw_data_id) REFERENCES store_daily_raw_data(id),
    FOREIGN KEY (metrics_id) REFERENCES store_computed_metrics(id)
);
CREATE INDEX IF NOT EXISTS idx_diag_date ON store_diagnosis_result(report_date);
CREATE INDEX IF NOT EXISTS idx_diag_store ON store_diagnosis_result(store_id);

CREATE TABLE IF NOT EXISTS store_diagnosis_issue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_id INTEGER NOT NULL,
    issue_type TEXT NOT NULL,
    issue_name TEXT NOT NULL,
    severity INTEGER NOT NULL DEFAULT 5,
    priority INTEGER NOT NULL DEFAULT 2,
    data_evidence TEXT DEFAULT '{}',
    root_cause TEXT DEFAULT '',
    root_cause_detail TEXT DEFAULT '',
    library_ref TEXT DEFAULT '{}',
    today_action TEXT DEFAULT '',
    day15_action TEXT DEFAULT '',
    manager_confirm TEXT DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (diagnosis_id) REFERENCES store_diagnosis_result(id)
);
CREATE INDEX IF NOT EXISTS idx_issue_diag ON store_diagnosis_issue(diagnosis_id);

CREATE TABLE IF NOT EXISTS customer_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL DEFAULT 'default_store',
    name TEXT NOT NULL,
    nickname TEXT DEFAULT '',
    phone TEXT NOT NULL,
    gender TEXT DEFAULT '女',
    age_range TEXT DEFAULT '',
    skin_type TEXT DEFAULT '',
    source_channel TEXT DEFAULT '',
    first_visit_date TEXT,
    customer_no TEXT,
    total_spent DECIMAL(12,2) DEFAULT 0,
    total_visits INTEGER DEFAULT 0,
    avg_order_value DECIMAL(12,2) DEFAULT 0,
    monthly_visit_freq DECIMAL(8,2) DEFAULT 0,
    last_visit_date TEXT,
    visit_last_30_days INTEGER DEFAULT 0,
    remaining_project_amount DECIMAL(12,2) DEFAULT 0,
    consumption_years INTEGER DEFAULT 0,
    rfm_label TEXT DEFAULT '',
    preferred_projects TEXT DEFAULT '',
    preferred_staff TEXT DEFAULT '',
    preferred_time TEXT DEFAULT '',
    price_sensitivity TEXT DEFAULT '',
    comm_preference TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(store_id, phone)
);
CREATE INDEX IF NOT EXISTS idx_customer_phone ON customer_profile(phone);
CREATE INDEX IF NOT EXISTS idx_customer_last_visit ON customer_profile(last_visit_date);
CREATE INDEX IF NOT EXISTS idx_customer_store ON customer_profile(store_id);

CREATE TABLE IF NOT EXISTS customer_project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    project_name TEXT NOT NULL,
    project_type TEXT NOT NULL,
    purchase_date TEXT NOT NULL,
    total_quantity INTEGER NOT NULL DEFAULT 1,
    total_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
    unit_amount DECIMAL(12,2) DEFAULT 0,
    used_quantity INTEGER DEFAULT 0,
    remaining_quantity INTEGER DEFAULT 0,
    expiry_date TEXT,
    responsible_staff TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customer_profile(id)
);
CREATE INDEX IF NOT EXISTS idx_cp_customer ON customer_project(customer_id);
CREATE INDEX IF NOT EXISTS idx_cp_status ON customer_project(status);

CREATE TABLE IF NOT EXISTS customer_home_product (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    product_type TEXT DEFAULT '',
    brand TEXT DEFAULT '',
    specification TEXT DEFAULT '',
    purchase_date TEXT NOT NULL,
    estimated_cycle INTEGER DEFAULT 30,
    estimated_end_date TEXT,
    usage_progress TEXT DEFAULT '',
    remaining_estimate TEXT DEFAULT '',
    usage_feedback TEXT DEFAULT '',
    repurchase_status TEXT DEFAULT 'normal',
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customer_profile(id)
);
CREATE INDEX IF NOT EXISTS idx_chp_customer ON customer_home_product(customer_id);
CREATE INDEX IF NOT EXISTS idx_chp_repurchase ON customer_home_product(repurchase_status);

CREATE TABLE IF NOT EXISTS customer_demand (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    demand_desc TEXT NOT NULL,
    demand_type TEXT DEFAULT '',
    related_project TEXT DEFAULT '',
    progress_score INTEGER DEFAULT 0,
    created_at_service TEXT,
    last_updated_at_service TEXT,
    created_by_staff TEXT DEFAULT '',
    responsible_staff TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    notes TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customer_profile(id)
);
CREATE INDEX IF NOT EXISTS idx_cd_customer ON customer_demand(customer_id);
CREATE INDEX IF NOT EXISTS idx_cd_type ON customer_demand(demand_type);
CREATE INDEX IF NOT EXISTS idx_cd_status ON customer_demand(status);

CREATE TABLE IF NOT EXISTS customer_warning (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    warning_type TEXT NOT NULL,
    warning_level TEXT NOT NULL,
    warning_source TEXT NOT NULL,
    warning_desc TEXT NOT NULL,
    is_resolved INTEGER DEFAULT 0,
    resolved_at TIMESTAMP,
    resolved_by TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customer_profile(id)
);
CREATE INDEX IF NOT EXISTS idx_cw_customer ON customer_warning(customer_id);
CREATE INDEX IF NOT EXISTS idx_cw_level ON customer_warning(warning_level);
CREATE INDEX IF NOT EXISTS idx_cw_resolved ON customer_warning(is_resolved);

CREATE TABLE IF NOT EXISTS customer_follow_task (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    warning_id INTEGER,
    task_desc TEXT NOT NULL,
    assigned_staff TEXT DEFAULT '',
    priority INTEGER DEFAULT 2,
    status TEXT DEFAULT 'pending',
    due_date TEXT,
    completed_at TIMESTAMP,
    result_note TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customer_profile(id),
    FOREIGN KEY (warning_id) REFERENCES customer_warning(id)
);

CREATE TABLE IF NOT EXISTS store_action_task (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL DEFAULT 'default_store',
    report_date TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 2,
    source_type TEXT DEFAULT '',
    source_id TEXT DEFAULT '',
    related_customer_id INTEGER,
    related_staff TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deadline TIMESTAMP,
    completed_at TIMESTAMP,
    review_note TEXT DEFAULT '',
    is_throttled_to_p1 INTEGER NOT NULL DEFAULT 0,
    keep_red_tag INTEGER NOT NULL DEFAULT 0,
    merged_warning_count INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (related_customer_id) REFERENCES customer_profile(id)
);
CREATE INDEX IF NOT EXISTS idx_task_date ON store_action_task(report_date);
CREATE INDEX IF NOT EXISTS idx_task_priority ON store_action_task(priority);
CREATE INDEX IF NOT EXISTS idx_task_status ON store_action_task(status);

CREATE TABLE IF NOT EXISTS daily_demand_board (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL DEFAULT 'default_store',
    board_date TEXT NOT NULL,
    board_data TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(store_id, board_date)
);

CREATE TABLE IF NOT EXISTS daily_review (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL DEFAULT 'default_store',
    report_date TEXT NOT NULL,
    review_content TEXT DEFAULT '',
    completed_tasks TEXT DEFAULT '[]',
    unfinished_tasks TEXT DEFAULT '[]',
    tomorrow_actions TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(store_id, report_date)
);
CREATE INDEX IF NOT EXISTS idx_review_date ON daily_review(report_date);

CREATE TABLE IF NOT EXISTS store_benchmark_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id TEXT NOT NULL DEFAULT 'default_store',
    store_type TEXT DEFAULT 'mature_store',
    store_stage TEXT DEFAULT 'mature',
    staff_count INTEGER DEFAULT 0,
    monthly_target DECIMAL(12,2) DEFAULT 0,
    avg_order_target DECIMAL(12,2) DEFAULT 0,
    per_capita_target DECIMAL(12,2) DEFAULT 0,
    new_customer_ratio_green_low DECIMAL(5,2) DEFAULT 15.00,
    new_customer_ratio_green_high DECIMAL(5,2) DEFAULT 30.00,
    return_customer_ratio_green_low DECIMAL(5,2) DEFAULT 70.00,
    return_customer_ratio_green_high DECIMAL(5,2) DEFAULT 85.00,
    conversion_rate_green DECIMAL(5,2) DEFAULT 60.00,
    repurchase_rate_green DECIMAL(5,2) DEFAULT 50.00,
    appointment_arrival_rate_green DECIMAL(5,2) DEFAULT 80.00,
    complaint_risk_max DECIMAL(8,2) DEFAULT 5.00,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(store_id)
);

-- 补丁5：高频查询复合索引
CREATE INDEX IF NOT EXISTS idx_cw_customer_resolved ON customer_warning(customer_id, is_resolved);
CREATE INDEX IF NOT EXISTS idx_task_store_date_priority_status ON store_action_task(store_id, report_date, priority, status);
CREATE INDEX IF NOT EXISTS idx_cd_customer_type_status ON customer_demand(customer_id, demand_type, status);
CREATE INDEX IF NOT EXISTS idx_cp_customer_status_remaining_expiry ON customer_project(customer_id, status, remaining_quantity, expiry_date);
CREATE INDEX IF NOT EXISTS idx_chp_customer_repurchase_enddate ON customer_home_product(customer_id, repurchase_status, estimated_end_date);
"""

# 补丁5 中 idx_cw_store_level_resolved 含 store_id，但 customer_warning 无 store_id 列，
# 改为按 customer+level+resolved 覆盖（store 维度经 customer 关联），见下方补充索引。
SCHEMA += """
CREATE INDEX IF NOT EXISTS idx_cw_customer_level_resolved ON customer_warning(customer_id, warning_level, is_resolved);
"""


def connect():
    """打开独立 SQLite 连接并确保建表（幂等）。"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def table_names():
    """返回本模块管理的 14 张表，用于 smoke 校验。"""
    return [
        "store_daily_raw_data", "store_computed_metrics", "store_diagnosis_result",
        "store_diagnosis_issue", "store_action_task", "customer_profile",
        "customer_project", "customer_home_product", "customer_demand",
        "customer_warning", "customer_follow_task", "daily_demand_board",
        "daily_review", "store_benchmark_config",
    ]
