# V0.1.3 后端 · 阈值小提交阶段 复审说明

> 对应扣子代码审查「有条件通过」后置 4 项。**仅小修，未扩功能。**
> 代码 HEAD（复审对象）：`2949888`（基础 `68263a1`）｜分支 `store-manager-v0.1.3-backend`（未 push）

## 修复 4 项（均来自审查报告前置条件）

### 1. 4 个业务阈值配置化（移入 StoreBenchmarkConfig，删除硬编码）
- `store_benchmark_config` 新增列并写入默认值（旧测试库自动 `ALTER` 补列）：
  | 阈值 | 列 | 默认值 |
  |------|----|-----|
  | 客流·日客流下限 | `traffic_visits_min` | 20 |
  | 新客承接·健康线 | `new_conversion_rate_green` | 40 |
  | 锁客·充值占比健康线 | `recharge_ratio_green` | 20 |
  | 项目结构·主推占比健康线 | `main_project_ratio_green` | 40 |
- `diagnosis_v013.py` 删除 `RULE_DEFAULTS`，4 条规则改从 `cfg` 读取；
- 客流规则按吴哥暂定改为 **`daily_visits < 20` 且 `new_customer_ratio < 15%`**（复用 `new_customer_ratio_green_low`）；
- GET/PUT `/benchmark-config` 可读可调这 4 个阈值。

### 2. generate_today_tasks 幂等保护（不丢已完成状态）
- 取消「DELETE 当日 customer_ops 任务后重建」；
- 改为按 `source_id` **upsert**：已存在则只刷新展示/限流字段、**保留 status/completed_at/review_note**；未出现的旧候选——**已完成的保留**，仅清未完成的过期候选；
- smoke 验证：标记 done 后重复 generate，该任务仍为 `done`。

### 3. 时区统一东八区
- 新增 `_util_v013.py`：`now_cst()/today_cst()/now_iso_cst()`（UTC+8）；
- `customer_ops_v013` / `tasks_v013` / `pipeline_v013` 全部 `datetime.now()` → 东八区；
- 日期相减改用 `.date()`，避免 aware/naive 混算。

### 4. store_id 输入校验（非空 + 长度 + 禁特殊字符）
- 规则：`^[A-Za-z0-9_-]{1,64}$`，非法 → **400**；
- 覆盖 13 个端点（9 query 用 `Depends(valid_store_id)`，4 body 调 `_check_store_id(req.store_id)`）；
- 不做复杂权限系统，不扩功能。

## 验证
- isolated router smoke：**35 PASS / 0 FAIL**（含阈值×4、store_id 校验×3、幂等×1 新增校验）
- 完整 main.py app 级 smoke：**9 PASS / 0 FAIL**
- 时区：`now_cst().utcoffset()=8:00`；阈值入库确认；`RULE_DEFAULTS` 已删除。
- 无 5xx / traceback。

## 变更文件（仅后端代码 + smoke）
新增 `_util_v013.py`；改 `db_v013.py` / `diagnosis_v013.py` / `customer_ops_v013.py` / `tasks_v013.py` / `pipeline_v013.py` / `router_v013.py` / `smoke_test_v013.py`。
> 未动主库、未动 V0.1.1、未动 18080/18081、未部署、未 push、未动 MWUZS-MINIAPP。

## 红线自查
未 push / 未 merge / 未部署 / 未 scp / 未动 18080 / 未动 18081 / 未动 V0.1.1 / 未动生产库 / 未改 Nginx / 未进前端 / 未进 Qoder / 未动小程序 ✅
