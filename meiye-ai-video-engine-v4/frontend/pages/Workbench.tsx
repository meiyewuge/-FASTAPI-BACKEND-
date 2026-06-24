/**
 * 工作台 —— 整个系统唯一的核心界面（skeleton）。
 *
 * 结构（严格极简，不允许复杂化）：
 *   [输入框] 请输入视频需求（AI 自动理解）
 *   [🎬 生成母视频 A台]  [🔁 生成裂变视频 B台]
 *   [任务状态区] 进行中 / 已完成 / 可下载 / 可分发
 *   [历史视频] 母视频列表 / 裂变视频列表
 */
import { useState } from "react";
import { aGenerate } from "../api/client";
// 单条入口用 aGenerate；一句话批量用 generate；B台裂变需选中母视频传 source_video_id。

export default function Workbench() {
  const [prompt, setPrompt] = useState("");

  return (
    <div className="workbench">
      <h1>美业AI视频系统 V4.0</h1>

      <textarea
        placeholder="请输入视频需求（AI 自动理解）……"
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
      />

      <div className="actions">
        <button onClick={() => aGenerate(prompt)}>🎬 生成母视频（A台）</button>
        {/* B台需先选中一条母视频传 source_video_id，此处为骨架占位 */}
        <button onClick={() => alert("请在母视频列表选一条后裂变（B台）")}>🔁 生成裂变视频（B台）</button>
      </div>

      {/* 任务状态区：进行中 / 已完成 / 可下载 / 可分发 —— TODO 接 /api/tasks */}
      <section className="task-status">{/* skeleton */}</section>

      {/* 历史视频：母视频列表 / 裂变视频列表 —— TODO 接 /api/videos */}
      <section className="history">{/* skeleton */}</section>
    </div>
  );
}
