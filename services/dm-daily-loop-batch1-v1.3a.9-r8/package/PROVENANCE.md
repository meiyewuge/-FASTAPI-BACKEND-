# PROVENANCE — DM Daily Loop Batch 1

## V1.3A.9-R8 (Stage C — Claude Code independent final audit + fix)
- 输入基线 R7 (完整生产基线): SHA-256 `12c7bdf68a21d77cbd5046c12e5ba9e8f9caba39b9ac3030ce387232eee41eb3`
- 智谱阶段 B-R1 证据包 (仅两脚本作为候选补丁): SHA-256 `89cecde53925ec4719147bc721a97ad6fc4805f9c2bd65981f3dd50b5d233768`
- 修改前封存审计快照: `CLAUDE_R8_PRE_EDIT_INDEPENDENT_AUDIT.md/.json` (SEALED_PRE_EDIT/SEAL.txt)
- 独立审计结论: `GO_FIX` — 12/12 已知阻断全部独立确认; 智谱 13/13 判为 MISLEADING (5 项假绿)

### R7 → R8 修复 (仅证据/检测器/构建层, 未改冻结生产代码)
1. **P0-1** failure code 执法: BLOCKED 需检测器输出结构化语义 failure_code (∈ 允许集) 且 hits_match, 不再只看 exit 1
2. **P0-2** m2 改为 SQL 合法 no-op `THEN 1`: schema 有效、trigger 存在、跨店写入真实成功 → `E-CROSS-STORE-SEMANTIC-BYPASS`
3. **P0-3** m6 special 完整删除 trigger 块: schema 仍可初始化、目标 trigger 缺失 → `E-CROSS-STORE-TRIGGER-MISSING`
4. **P0-4** m5 `_authorize('write')→_require_context`: 保留 ctx=None→PermissionError, 去除 role/store 授权, staff/cross 写入成功 → `E-VAULT-WRITE-AUTH-BYPASS`
5. **P0-5** m9 `_authorize('rotate')→_require_context`: manager/cross rotate 成功 → `E-VAULT-ROTATE-AUTH-BYPASS`
6. **P0-6** m10 语法合法 `True`: `if not True:` 真正绕过 Provider 校验 → `E-RECOVERY-PROVIDER-VERIFY-BYPASS`
7. **P0-7** Truth Gate 异常三分类 (exit 0/1/2/3): 检测器不再把任意异常当安全 FAIL; vault 24 项逐项隔离
8. **P0-8** security 检测器构造真实业务模型对象调用真实生产写入口, 只接受 ValueError; TypeError 等为 ERROR
9. **P0-9** cross_store 只接受 `sqlite3.IntegrityError` 且断言 E-SCOPE, 其它为 ERROR
10. **P0-10** 报告字段闭合: started_at/ended_at/duration_ms/timed_out/signal, argv detector_command, normal-before/after 原始日志+SHA, 选择器自测
11. **P0-11** 单一构建产出闭合 Manifest (0/0/0) + 完整交付物清单
12. **P0-12** 可复现: build_id 由顶层构建注入; 默认 (replay) 模式只比较稳定签名 (排除 volatile)

### 允许修改文件 (实际修改)
- `run_truth_gate.py` — 结构化检测器 + 异常三分类 + 选择器自测
- `run_mutation_tests.py` — 语义修正 mutation + failure-code 执法 + 报告闭合 + 稳定签名比较
- `build_release.py` — 真实结果构建 (无硬编码 PASS) + 打包
- `PROVENANCE.md`, `V1.3A.9_R7_TO_R8_DIFF.md`, 三份 JSON 报告 (由真实结果生成)

### 未修改 (冻结)
- `app/daily_loop/services/*` 生产代码、migration 生产 SQL、`tests/*` 业务断言、restore 故障注入业务语义、vendor
- (mutation 只在临时副本上修改生产文件, 不改正式基线)

### 依赖
- cryptography==49.0.0, cffi==2.1.0, pycparser==3.0.0

### 当前状态 (仅在独立审计 + 修复 + 单一构建 + 最终 ZIP 反向复跑全部通过后写)
`DM_DAILY_LOOP_BATCH1_V1_3A_9_R8_READY_FOR_HUMAN_MERGE_REVIEW`
