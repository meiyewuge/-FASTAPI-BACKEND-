# CLAUDE_R8_R1_CLOSURE_REPORT

- **轮次**: V1.3A.9-R8-R1（GPT 独立复审 NO-GO → Claude 定点闭合）
- **时间**: 2026-07-17 (UTC)
- **环境**: Python 3.11.15；cryptography 49.0.0 / cffi 2.1.0 / pycparser 3.0.0
- **最终 ZIP**: `ZHIPU_DM_DAILY_LOOP_BATCH1_V1_3A_9_R8_R1_EVIDENCE_INTEGRITY_FINAL_CLOSURE.zip`
- **最终 ZIP SHA-256**: `e1aabb13d10b3dfa3c0f1d266434bcad70ff46268744ff852967aaac239322fd`
- **build_id**: `r8r1-20260717T080700Z`（贯穿全部 5 份报告 + build 报告 + attestation）

## GPT 7 项 P0 处置

| # | 处置 | 证据 |
|---|------|------|
| **P0-1** 最终 ZIP 未交付 | 已重建新 ZIP（R8-R1，新 SHA）并**交付 ZIP 本体** + 新 attestation；旧 SHA 作废 | ZIP SHA `e1aabb13…`；attestation verdict PASS |
| **P0-2** manifest 检查 ResourceWarning | `check_manifest` 改上下文管理器 + `_sha256_file` helper；`PYTHONWARNINGS=always` 下 gate/主测试/smoke/fault **ResourceWarning=0**；machine report 记录 `resource_warnings: 0`（构建校验，非 0 即 FATAL） | machine_test_report.resource_warnings=0 |
| **P0-3** wrong-key 任意异常假绿 | `tests/run_tests.py` 单一断言 → `assertRaises(InvalidTag)`；vault item 24 只接受 `InvalidTag` 且验证原库行数 + 文件 SHA 不变 | item 24 observed=`InvalidTag,rows&sha_unchanged` |
| **P0-4** expires_at-1 正向边界假绿 | vault 拆分 `deny`/`allow` runner；第 **6/16/23 正向不变量**：`PermissionError` 判 **FAIL**（不再当 PASS） | item 6 expected=succeed；24 项结构化 |
| **P0-5** build_id 未贯穿 | 同一 build_id 写入 machine/mutation/security/fault/change/build 全部报告 + attestation；构建结束校验一致，不一致非零退出不打包 | "build_id consistent across 5 reports" |
| **P0-6** change_evidence 基线错误 | 基线改用封存 **R7** `r7_baseline_manifest.json`（R7 SHA `12c7bdf6…`）；逐文件 before/after SHA。实测 **11 改 + 2 新** | changed=11（run_truth_gate/run_mutation_tests/build_release/tests_run_tests/PROVENANCE + 6 报告） |
| **P0-7** security_invariants 非 1—24 闭合 | 由 vault detector **实时 1—24 结构化 items** 派生；构建校验键集精确 1..24 且全 PASS | key_set_is_1_to_24=True, all_held=True, 24 items |

## P1 处置

- **P1-1 Manifest 文件数口径**: 以新 ZIP 真实值为准 = **48 文件**（不再沿用旧数字）。
- **P1-2 原始日志可回算**: 最终 ZIP **包含** `evidence/logs/`（normal-before/after + 每 mutation stdout/stderr）；每份报告内 log SHA 可对 ZIP 内实际日志逐一重算。
- **P1-3 GitHub CI 状态**: **当前仅本地/独立复跑，PR #3 head commit 无 GitHub Actions run**。未新增 CI workflow（避免影响仓库其它 PR）——如需平台 CI 需人工另行决定并接受此风险。本报告不声称平台 CI 已验证。

## 强制验收结果（clean venv，独立复跑）

| 项 | 结果 |
|----|------|
| Truth Gate | 9/9 PASS |
| `--selftest` | 全 10 选择器 PASS |
| 主测试 / smoke / vendor / fault | exit 0（88 / 26 / 66 / 7） |
| Mutation | **13/13 BLOCKED**，0 FALSE_GREEN，0 ERROR，sequence PASS |
| Mutation 稳定签名复跑 | PASS（volatile-free） |
| ResourceWarning（gate+3 套测试，PYTHONWARNINGS=always） | **0** |
| Manifest | 0 mismatch / 0 missing / 0 unlisted（48 文件） |
| security invariants | 1—24 键集完整、全 PASS |
| build_id 一致性 | 6 报告 + attestation 同一 build_id |

## 最终 ZIP 反向复跑（外置，全新解压）

`truth_gate → selftest → mutation(replay,稳定签名匹配) → truth_gate → main/smoke/vendor/fault`
—— **全部 exit 0**，attestation **verdict PASS**，绑定 ZIP SHA `e1aabb13…` + build_id + 每步 argv/时间/exit/log SHA。

## 冻结范围
未改 `app/daily_loop/services/*`、migration SQL、restore 故障注入业务语义、vendor；`tests/run_tests.py` 仅按 GPT 授权改动**单一 wrong-key 断言**。

## 状态
`DM_DAILY_LOOP_BATCH1_V1_3A_9_R8_R1_READY_FOR_HUMAN_MERGE_REVIEW`（更新 PR #3，不合并 main）。
