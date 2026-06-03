# 大模型接入说明

系统通过 OpenAI-compatible 接口调用大模型。

环境变量：

```text
LLM_PROVIDER=deepseek
LLM_API_KEY=your_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
```

如果 `LLM_API_KEY` 为空，系统会使用本地模板报告，不影响流程测试。

大模型原则：

1. 不算分；
2. 不改分；
3. 不编造数据；
4. 只基于结构化结果生成报告文案。

提示词在 `backend/app/ai.py`。
