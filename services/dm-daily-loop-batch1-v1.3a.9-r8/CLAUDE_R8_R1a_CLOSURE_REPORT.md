# CLAUDE_R8_R1a_CLOSURE_REPORT

- **轮次**: V1.3A.9-R8-R1a（GPT 短终审：核心代码 GO / 证据包 1×P0 + 1×P1 → Claude 仅改证据·构建层闭合）
- **时间**: 2026-07-17 (UTC)
- **最终 ZIP**: `ZHIPU_DM_DAILY_LOOP_BATCH1_V1_3A_9_R8_R1a_EVIDENCE_INTEGRITY_FINAL_CLOSURE.zip`
- **最终 ZIP SHA-256**: `e6d6a1f53fcf3c329683ef4bf8336847d1d1b1a0cc8fac5d0ea33fca2ac957b7`
- **Companion 复跑证据 ZIP**: `ZHIPU_DM_DAILY_LOOP_BATCH1_V1_3A_9_R8_R1A_REPLAY_EVIDENCE.zip`
- **Companion SHA-256**: `18dc1f327651ec268371cc4ae6b1ebc385fbf5cf64ecc72f25f83759a7dac7e2`
- **build_id**: `r8r1a-20260717T092132Z`（贯穿 6 报告 + attestation）
- **旧 ZIP `e1aabb13…` → SUPERSEDED**

## P0（change_evidence final SHA 不真实 / 自引用）— 已闭合

根因：`build_execution_report.json` 在 change_evidence 之后写入、`change_evidence.json` 试图记录自身 SHA。

修复（非自引用设计）：
1. `changed_vs_r7_baseline` 只记录**稳定可回算**的源码/测试/控制文件与最终前已定稿的报告 —— **9 项**，全部 current_sha 可对最终 ZIP 逐字节回算；
2. `change_evidence.json` **不再记录自身** current_sha；
3. `build_execution_report.json`、`change_evidence.json`、`manifest.json` 移入 `generated_artifacts`，由最终 `manifest.json` / attestation 的 ZIP SHA 绑定，不伪称已回算；
4. **构建结束机器校验**：逐项重算 `changed_vs_r7_baseline` current_sha，任一不一致即 FATAL 不打包；并校验 `new_files`（2 项）确不在 R7 manifest 且最终存在；
5. GPT §六 校验脚本在**最终 ZIP 全新解压后独立通过** → `CHANGE_EVIDENCE_FINAL_SHA_CLOSURE_PASS`。

## P1（原始日志可回算）— 采用方案 A 闭合

- 构建：`run_step()` 将每步 stdout+stderr 写入 `evidence/logs/build/<step>.log`（随主 ZIP）；`build_execution_report.json` 记录 `log_path`+`log_sha256`。**7/7 build step 日志可从 ZIP 逐一回算**（0 missing / 0 mismatch）。
- 复跑：外置 replay 每步日志写入 companion `..._R8_R1A_REPLAY_EVIDENCE.zip`；attestation 记录每步 `log_path_in_companion`+`log_sha256`。**8/8 replay step 日志**齐备。
- 加上原有 28 个 mutation/normal 日志（`mutation_report.json` 可回算），日志声明现已与事实一致。

## 独立复跑（最终 ZIP 全新解压）

| 项 | 结果 |
|----|------|
| change_evidence final-SHA 闭合（GPT §六） | **PASS**（9 可回算 + 2 new，无自引用） |
| build step 日志可回算 | 7/7（0 missing/mismatch） |
| replay step 日志（companion） | 8/8 |
| Truth Gate / selftest | 9/9 / 10/10 |
| 主/smoke/vendor/fault | exit 0（88/26/66/7） |
| Mutation | 13/13 BLOCKED, stable replay PASS |
| Manifest | 0/0/0（48 文件） |
| security invariants | 1—24 全 PASS |
| ResourceWarning | 0 |
| build_id 一致性 | 6 报告 + attestation 同一 |
| **attestation verdict** | **PASS** |

## 修改边界（仅证据/构建层）
本轮仅改 `build_release.py`（run_step 日志 + change_evidence 重设计 + 结束闭合校验）、`PROVENANCE.md`，及由此重生成的报告/manifest/attestation。
**未触碰** `run_truth_gate.py`、`run_mutation_tests.py`、`tests/*`、`app/daily_loop/services/*`、migration、vendor、fault-injection 语义。

## 状态
`DM_DAILY_LOOP_BATCH1_V1_3A_9_R8_R1a_READY_FOR_HUMAN_MERGE_REVIEW`（更新 PR #3，不合并 main）。
交付：新 ZIP 本体 + companion 复跑证据 ZIP + 新 attestation + 本报告。
