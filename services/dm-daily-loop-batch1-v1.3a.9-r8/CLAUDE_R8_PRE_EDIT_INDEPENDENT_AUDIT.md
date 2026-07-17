# CLAUDE_R8_PRE_EDIT_INDEPENDENT_AUDIT

> **封存快照 — 生成于任何编辑之前。** 本文件与其 `.json` 版本在修改开始前定稿并计算自身 SHA-256，后续不再改写。

- **审计方**: Claude Code（独立终审，pre-edit 快照）
- **审计时间**: 2026-07-13 (UTC)
- **环境**: Python 3.11.15；cryptography 49.0.0 / cffi 2.1.0 / pycparser 3.0.0（与 R7 锁定一致）

## 输入与 SHA（均已核验一致）

| 文件 | SHA-256 | 与工单一致 |
|------|---------|-----------|
| R7 完整生产基线 zip | `12c7bdf68a21d77cbd5046c12e5ba9e8f9caba39b9ac3030ce387232eee41eb3` | ✅ |
| 阶段 B-R1 证据包 zip | `89cecde53925ec4719147bc721a97ad6fc4805f9c2bd65981f3dd50b5d233768` | ✅ |

审计副本 = R7 完整基线 + 覆盖阶段 B-R1 的 `run_truth_gate.py`、`run_mutation_tests.py`（严格按工单 §1.2）。

## 对智谱 "13/13" 结论的判定

**MISLEADING / 不可信。** 独立复跑确实显示 13/13 "BLOCKED"，但其中 **5 项（m2/m5/m6/m9/m10）为 FALSE GREEN**：
检测器用 `except Exception: return False` 把 SQL `OperationalError` / `AttributeError` / `SyntaxError` 一律转成 "BLOCKED"，
安全不变量根本没被真正触发。且诚实的默认复跑因 volatile `build_id`/duration 直接 **exit 1**（"bundled report does not match current run"），
交付证据包**通不过自身 Replay**。

## 总结论：`GO_FIX`

12 项已知阻断**全部独立确认**。R7 生产基线（`app/daily_loop/services/*`、migrations、tests）稳固且未被触碰；
全部缺陷位于**允许修改**的证据/检测器/构建层（`run_truth_gate.py`、`run_mutation_tests.py`、`build_release.py`、报告）。
故可在授权范围内修复，无需改动冻结生产代码。

## 12 项已知阻断 — 逐项独立判定

| # | 标题 | 判定 | 关键证据（独立复现） |
|---|------|------|----------------------|
| **P0-1** | runner 只看 exit 1，未验证语义 failure code | ✅ CONFIRMED | `run_mutation_tests.py:187` `if exit_code==1 and hits_match`；`observed_failure_code=="exit 1"`，`expected_failure_code` 定义但不参与判定 |
| **P0-2** | m2 是无效 SQL 破坏，非跨店语义旁路 | ✅ CONFIRMED | `THEN SELECT 1` 置入 CASE → 无效 SQL。实测：`FAIL: schema init failed ...: OperationalError` |
| **P0-3** | m6 删 trigger 只造成 SQL 语法错误 | ✅ CONFIRMED | 仅注释 `CREATE TRIGGER` 行，遗留孤立 BEGIN/END。实测：`schema init failed: OperationalError` |
| **P0-4** | m5 未证明 write 授权旁路 | ✅ CONFIRMED | 实测：`AttributeError: 'NoneType' object has no attribute 'member_id'` —ctx=None 先崩，未达 staff/cross-store 写 |
| **P0-5** | m9 未真正绕过 rotate 授权 | ✅ CONFIRMED | 删 `_require_context` 后 `_authorize` 仍强制。实测：`AttributeError: ...store_id` |
| **P0-6** | m10 是语法错误，非 verifier mix | ✅ CONFIRMED | `True  # verifier mix` 注释掉了冒号。实测：`SyntaxError: expected ':' (vault_recovery_service.py, line 53)` |
| **P0-7** | vault 检测器把任意异常当安全 FAIL | ✅ CONFIRMED | `run_truth_gate.py:144` `except Exception: return False`（→ exit 1=BLOCKED）；24 项不隔离，首异常即中止。这是 m5/m9/m10 假绿的根因 |
| **P0-8** | security 检测器裸 except 假绿 | ✅ CONFIRMED | `run_truth_gate.py:93/97` `except: pass`；TypeError 被当"安全拒绝成功" |
| **P0-9** | cross-store 检测器吞所有异常 | ✅ CONFIRMED | `run_truth_gate.py:78` `except: pass`；且 `:302` `except (PermissionError, TypeError): pass` 纳入 TypeError |
| **P0-10** | 报告字段未闭合 | ✅ CONFIRMED | 缺 `started_at/ended_at/duration_ms/timed_out/signal`；`detector_command` 是字符串非 argv；normal-before/after 仅 exit code 无原始日志；无 selector 自测 |
| **P0-11** | 阶段 B-R1 证据 ZIP 不闭合 | ✅ CONFIRMED | manifest listed=69 / disk=32 / missing=41 / unlisted=`mutation_report.json`；缺 STAGE_B_R1_PROVENANCE、选择器自测、检测器矩阵、纠偏工单、normal 日志 |
| **P0-12** | 默认报告比较不可复现 | ✅ CONFIRMED | `BUILD_ID=uuid4()` 每次新生成 + 全 JSON 字节比较含 volatile。实测：干净复跑 exit 1 `bundled report does not match current run` |

## Mutation 语义真实性分层

- **真实/可信 BLOCKED（8）**：m1、m3、m4、m7、m8、m11、m12、m13
- **FALSE GREEN（异常驱动，5）**：m2、m5、m6、m9、m10

## 封存声明

本快照在**开始任何修改之前**定稿。两个审计文件（`.md`/`.json`）的自身 SHA-256 记录于 `SEAL.txt`，
副本存入只读封存目录 `SEALED_PRE_EDIT/`，最终交付将包含本原始快照。修复阶段（Stage B/C）不得改写本文件。
