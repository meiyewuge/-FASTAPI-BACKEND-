/**
 * 工作台 — 极简生产稳定版（UI 冻结）
 *
 * 固定结构：
 *  1. 顶部：租户 + 成本面板
 *  2. 输入区：文本框 + 一句话生成 / A台 / B台
 *  3. 任务状态区：清晰进度 + 重试
 *  4. 视频结果区：播放 / 下载
 *  5. 视频库：母视频 / 裂变视频 + 导出
 *  6. 产能指标（轻量数字卡片，非复杂图表）
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  generate,
  aGenerate,
  bGenerate,
  pollTask,
  listTasks,
  listVideos,
  costSummary,
  strategies as fetchStrategies,
  metricsOverview,
  retryTask,
  exportVideosCSV,
  getTenant,
  clearAuth,
  type TaskData,
  type VideoItem,
  type CostSummary,
  type StrategyItem,
  type MetricsOverview,
} from "../api/client";

// ---- 状态标签 ----
function statusLabel(s: string) {
  const map: Record<string, { text: string; cls: string }> = {
    pending: { text: "排队中", cls: "tag-pending" },
    running: { text: "生成中", cls: "tag-running" },
    done: { text: "已完成", cls: "tag-done" },
    failed: { text: "失败", cls: "tag-failed" },
  };
  const item = map[s] || { text: s, cls: "" };
  return <span className={`tag ${item.cls}`}>{item.text}</span>;
}

export default function Workbench() {
  const navigate = useNavigate();

  // ---- 状态 ----
  const [prompt, setPrompt] = useState("");
  const [generating, setGenerating] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [tasks, setTasks] = useState<TaskData[]>([]);
  const [activeTask, setActiveTask] = useState<TaskData | null>(null);
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [videoTab, setVideoTab] = useState<"mother" | "viral">("mother");
  const [cost, setCost] = useState<CostSummary | null>(null);
  const [metrics, setMetrics] = useState<MetricsOverview | null>(null);
  const [strats, setStrats] = useState<StrategyItem[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState("mix");
  const [selectedVideo, setSelectedVideo] = useState<VideoItem | null>(null);
  const [videoPage, setVideoPage] = useState(1);
  const [videoTotal, setVideoTotal] = useState(0);
  const [toast, setToast] = useState("");
  const pollRef = useRef(false);

  // ---- Toast ----
  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(""), 3000);
  };

  // ---- 加载初始数据 ----
  const loadDashboard = useCallback(async () => {
    const [costR, metricsR, tasksR, videosR, stratsR] = await Promise.all([
      costSummary(),
      metricsOverview(),
      listTasks(),
      listVideos("mother", 1, 20),
      fetchStrategies(),
    ]);
    if (costR.code === 0) setCost(costR.data);
    if (metricsR.code === 0) setMetrics(metricsR.data);
    if (tasksR.code === 0) setTasks(tasksR.data?.items || []);
    if (videosR.code === 0) {
      setVideos(videosR.data?.items || []);
      setVideoTotal(videosR.data?.total || 0);
    }
    if (stratsR.code === 0) setStrats(stratsR.data?.items || []);
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  // ---- 切换视频类型 ----
  const switchVideoTab = async (type: "mother" | "viral") => {
    setVideoTab(type);
    setVideoPage(1);
    const r = await listVideos(type, 1, 20);
    if (r.code === 0) {
      setVideos(r.data?.items || []);
      setVideoTotal(r.data?.total || 0);
    }
  };

  // ---- 翻页 ----
  const loadVideoPage = async (page: number) => {
    setVideoPage(page);
    const r = await listVideos(videoTab, page, 20);
    if (r.code === 0) {
      setVideos(r.data?.items || []);
      setVideoTotal(r.data?.total || 0);
    }
  };

  // ---- 轮询任务 ----
  const startPoll = async (taskId: string) => {
    pollRef.current = true;
    const r = await pollTask(
      taskId,
      (d) => {
        if (pollRef.current) setActiveTask({ ...d });
      },
      1500,
    );
    pollRef.current = false;
    if (r.code === 0 && r.data) {
      setActiveTask(r.data);
      showToast(r.data.status === "done" ? "视频生成完成!" : "任务失败");
    }
    loadDashboard();
  };

  // ---- 一句话生成 ----
  const handleGenerate = async () => {
    if (!prompt.trim()) {
      showToast("请输入视频需求");
      return;
    }
    setGenerating(true);
    setActiveTask(null);
    try {
      const r = await generate(prompt.trim());
      if (r.code === 0 && r.data) {
        const taskIds = r.data.plan?.task_ids || [];
        showToast(`已提交 ${taskIds.length} 个任务`);
        if (taskIds.length > 0) startPoll(taskIds[0]);
      } else if (r.code === 4029) {
        showToast("配额不足: " + r.msg);
      } else {
        showToast(r.msg || "生成失败");
      }
    } catch {
      showToast("网络异常");
    } finally {
      setGenerating(false);
    }
  };

  // ---- A台单条 ----
  const handleAGenerate = async () => {
    if (!prompt.trim()) {
      showToast("请输入视频需求");
      return;
    }
    setGenerating(true);
    setActiveTask(null);
    try {
      const r = await aGenerate(prompt.trim());
      if (r.code === 0 && r.data?.task_id) {
        showToast("A台任务已提交");
        startPoll(r.data.task_id);
      } else {
        showToast(r.msg || "A台生成失败");
      }
    } catch {
      showToast("网络异常");
    } finally {
      setGenerating(false);
    }
  };

  // ---- B台裂变 ----
  const handleBGenerate = async () => {
    if (!selectedVideo) {
      showToast("请先在视频列表中选择一条母视频");
      return;
    }
    setGenerating(true);
    setActiveTask(null);
    try {
      const r = await bGenerate(
        selectedVideo.video_id,
        5,
        selectedStrategy,
        prompt.trim() || undefined,
      );
      if (r.code === 0 && r.data?.task_id) {
        showToast("B台裂变任务已提交");
        startPoll(r.data.task_id);
      } else if (r.code === 4029) {
        showToast("配额不足: " + r.msg);
      } else {
        showToast(r.msg || "B台生成失败");
      }
    } catch {
      showToast("网络异常");
    } finally {
      setGenerating(false);
    }
  };

  // ---- 重试 ----
  const handleRetry = async (taskId: string) => {
    const r = await retryTask(taskId);
    if (r.code === 0) {
      showToast("已重新提交");
      startPoll(taskId);
    } else {
      showToast(r.msg || "重试失败");
    }
  };

  // ---- 导出 CSV ----
  const handleExport = async () => {
    setExporting(true);
    try {
      const ok = await exportVideosCSV({
        type: videoTab,
      });
      showToast(ok ? "导出成功，正在下载" : "导出失败");
    } catch {
      showToast("导出异常");
    } finally {
      setExporting(false);
    }
  };

  // ---- 退出 ----
  const handleLogout = () => {
    clearAuth();
    navigate("/login", { replace: true });
  };

  // ---- 费用预估（F2 核心）----
  // 从 metrics.videos_per_cost_unit 推导单条成本
  const costPerVideo = metrics && metrics.videos_per_cost_unit > 0
    ? 1 / metrics.videos_per_cost_unit
    : null;

  // 从输入文本中提取数量（如"10个" → 10），未识别默认 1
  const parseCount = (text: string): number => {
    const m = text.match(/(\d+)\s*[个条份张]/);
    return m ? parseInt(m[1], 10) : 1;
  };

  const batchCount = parseCount(prompt);
  const estimateBatch = costPerVideo ? costPerVideo * batchCount : null;
  const estimateA = costPerVideo; // 单条
  const estimateB = costPerVideo ? costPerVideo * 5 : null; // B台默认5条

  // ---- 批量下载（F8 关键）----
  const handleBatchDownload = (videoList: VideoItem[]) => {
    const downloadable = videoList.filter((v) => v.download_url);
    if (downloadable.length === 0) {
      showToast("没有可下载的视频");
      return;
    }
    downloadable.forEach((v, i) => {
      setTimeout(() => {
        const a = document.createElement("a");
        a.href = v.download_url;
        a.download = v.title || `视频_${v.video_id}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }, i * 300); // 间隔 300ms 避免浏览器拦截
    });
    showToast(`正在下载 ${downloadable.length} 个视频`);
  };

  const resultVideos = activeTask?.result?.videos || [];
  const progressPct = Math.round((activeTask?.progress || 0) * 100);

  return (
    <div className="workbench">
      {toast && <div className="toast">{toast}</div>}

      {/* ===== 1. 顶部栏 ===== */}
      <header className="wb-header">
        <div className="wb-header-left">
          <h1>美业AI视频系统</h1>
          <span className="tenant-badge">租户: {getTenant()}</span>
        </div>
        <div className="wb-header-right">
          {cost && (
            <div className="cost-panel">
              <span className="cost-label">剩余额度</span>
              <span className="cost-value">¥{cost.remaining?.toFixed(2) ?? "--"}</span>
              <span className="cost-sub">
                已用 ¥{cost.spend?.toFixed(2) ?? "0"} / 配额 ¥{cost.quota?.toFixed(2) ?? "0"}
              </span>
            </div>
          )}
          <button className="btn-logout" onClick={handleLogout}>退出</button>
        </div>
      </header>

      {/* ===== 2. 输入区 ===== */}
      <section className="wb-input">
        <textarea
          className="wb-textarea"
          placeholder="请输入视频需求（AI 自动理解），例如：帮我做10个广州美容院抗衰视频"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          disabled={generating}
        />
        <div className="wb-actions">
          <button
            className="btn btn-primary"
            onClick={handleGenerate}
            disabled={generating}
          >
            {generating ? "提交中..." : "⚡ 一句话批量生成"}
          </button>
          <button
            className="btn btn-a"
            onClick={handleAGenerate}
            disabled={generating}
          >
            🎬 A台·母视频
          </button>
          <button
            className="btn btn-b"
            onClick={handleBGenerate}
            disabled={generating || !selectedVideo}
            title={selectedVideo ? "" : "请先在下方视频列表选中一条母视频"}
          >
            🔁 B台·裂变
          </button>
        </div>
        {/* F2: 费用预估 */}
        {costPerVideo && prompt.trim() && (
          <div className="cost-estimate">
            <span className="cost-estimate-label">预估费用：</span>
            {batchCount > 1 && (
              <span>批量 {batchCount} 条 ≈ <strong>¥{estimateBatch!.toFixed(2)}</strong></span>
            )}
            <span className="cost-estimate-sep">|</span>
            <span>A台单条 ≈ ¥{estimateA!.toFixed(2)}</span>
            <span className="cost-estimate-sep">|</span>
            <span>B台5条 ≈ ¥{estimateB!.toFixed(2)}</span>
            <span className="cost-estimate-sep">|</span>
            <span className="cost-estimate-remaining">
              剩余额度 ¥{cost?.remaining?.toFixed(2) ?? "--"}
            </span>
          </div>
        )}
      </section>

      {/* ===== 3. 任务状态区 ===== */}
      <section className="wb-tasks">
        <h2>任务状态</h2>

        {/* 当前活跃任务 */}
        {activeTask && (
          <div className="active-task">
            <div className="task-header">
              <span className="task-id">{activeTask.task_id.slice(0, 8)}</span>
              <span className="task-type-badge">
                {activeTask.type === "a" ? "A台·母视频" : "B台·裂变"}
              </span>
              {statusLabel(activeTask.status)}
            </div>

            {/* 清晰进度条 + 百分比 */}
            {activeTask.status === "running" && (
              <div className="progress-section">
                <div className="progress-bar">
                  <div
                    className="progress-fill"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
                <span className="progress-text">{progressPct}%</span>
              </div>
            )}

            {activeTask.status === "pending" && (
              <p className="task-hint">任务排队中，请稍候...</p>
            )}

            {activeTask.error && (
              <div className="task-error">
                <span>{activeTask.error}</span>
                <button className="btn btn-sm" onClick={() => handleRetry(activeTask.task_id)}>
                  重试
                </button>
              </div>
            )}
          </div>
        )}

        {/* 生成结果视频 */}
        {resultVideos.length > 0 && (
          <div className="result-videos">
            <div className="result-header">
              <h3>生成结果（{resultVideos.length} 条）</h3>
              {resultVideos.some((v) => v.download_url) && (
                <button
                  className="btn btn-download-all"
                  onClick={() => handleBatchDownload(resultVideos)}
                >
                  📥 全部下载（{resultVideos.filter((v) => v.download_url).length}）
                </button>
              )}
            </div>
            <div className="video-grid">
              {resultVideos.map((v, i) => (
                <div key={v.video_id || i} className="video-card">
                  <div className="video-preview">
                    {v.download_url ? (
                      <video src={v.download_url} controls preload="metadata" />
                    ) : (
                      <div className="video-placeholder">视频加载中</div>
                    )}
                  </div>
                  <div className="video-info">
                    <span className="video-type-badge">
                      {v.type === "mother" ? "母视频" : "裂变"}
                    </span>
                    {v.strategy && <span className="video-strategy">{v.strategy}</span>}
                    <div className="video-actions">
                      {v.download_url && (
                        <a href={v.download_url} download className="btn btn-sm">下载</a>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 近期任务列表 */}
        {tasks.length > 0 && (
          <div className="task-list">
            <h3>近期任务</h3>
            <table className="task-table">
              <thead>
                <tr>
                  <th>编号</th>
                  <th>类型</th>
                  <th>状态</th>
                  <th>进度</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {tasks.slice(0, 10).map((t) => (
                  <tr
                    key={t.task_id}
                    className={activeTask?.task_id === t.task_id ? "active-row" : ""}
                    onClick={() => setActiveTask(t)}
                  >
                    <td>{t.task_id.slice(0, 8)}</td>
                    <td>{t.type === "a" ? "A台" : "B台"}</td>
                    <td>{statusLabel(t.status)}</td>
                    <td>{Math.round((t.progress || 0) * 100)}%</td>
                    <td>
                      {t.status === "failed" && (
                        <button
                          className="btn btn-sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            handleRetry(t.task_id);
                          }}
                        >
                          重试
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ===== 4 & 5. 视频库 + 策略选择 + 导出 ===== */}
      <section className="wb-videos">
        <div className="video-section-header">
          <h2>视频库</h2>
          <div className="video-section-actions">
            <div className="video-tabs">
              <button
                className={videoTab === "mother" ? "tab active" : "tab"}
                onClick={() => switchVideoTab("mother")}
              >
                母视频
              </button>
              <button
                className={videoTab === "viral" ? "tab active" : "tab"}
                onClick={() => switchVideoTab("viral")}
              >
                裂变视频
              </button>
            </div>
            <button
              className="btn btn-export"
              onClick={handleExport}
              disabled={exporting || videos.length === 0}
            >
              {exporting ? "导出中..." : "📥 导出CSV"}
            </button>
          </div>
        </div>

        {/* B台策略选择 */}
        {selectedVideo && strats.length > 0 && (
          <div className="strategy-bar">
            <span>裂变策略：</span>
            {strats.map((s) => (
              <button
                key={s.key}
                className={selectedStrategy === s.key ? "strat-btn active" : "strat-btn"}
                onClick={() => setSelectedStrategy(s.key)}
                title={s.goal}
              >
                {s.label}
              </button>
            ))}
          </div>
        )}

        {selectedVideo && (
          <p className="selected-hint">
            已选母视频：{selectedVideo.title || `#${selectedVideo.video_id}`}
            <button className="btn-text" onClick={() => setSelectedVideo(null)}>取消选择</button>
          </p>
        )}

        {videos.length === 0 ? (
          <div className="empty-state">暂无{videoTab === "mother" ? "母视频" : "裂变视频"}记录</div>
        ) : (
          <>
            <div className="video-grid">
              {videos.map((v) => (
                <div
                  key={v.video_id}
                  className={`video-card ${selectedVideo?.video_id === v.video_id ? "selected" : ""}`}
                  onClick={() =>
                    setSelectedVideo(selectedVideo?.video_id === v.video_id ? null : v)
                  }
                >
                  <div className="video-preview">
                    {v.download_url ? (
                      <video src={v.download_url} controls preload="metadata" />
                    ) : (
                      <div className="video-placeholder">{v.title || "视频"}</div>
                    )}
                  </div>
                  <div className="video-info">
                    <span className="video-title">{v.title || `视频 #${v.video_id}`}</span>
                    <div className="video-actions">
                      {v.download_url && (
                        <a
                          href={v.download_url}
                          download
                          className="btn btn-sm"
                          onClick={(e) => e.stopPropagation()}
                        >
                          下载
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            {videoTotal > 20 && (
              <div className="pagination">
                <button disabled={videoPage <= 1} onClick={() => loadVideoPage(videoPage - 1)}>
                  上一页
                </button>
                <span>{videoPage} / {Math.ceil(videoTotal / 20)}</span>
                <button
                  disabled={videoPage >= Math.ceil(videoTotal / 20)}
                  onClick={() => loadVideoPage(videoPage + 1)}
                >
                  下一页
                </button>
              </div>
            )}
          </>
        )}
      </section>

      {/* ===== 6. 产能指标（轻量数字，非复杂图表）===== */}
      {metrics && (
        <section className="wb-metrics">
          <h2>产能概览</h2>
          <div className="metrics-grid">
            <div className="metric-card">
              <span className="metric-value">{metrics.total_videos ?? 0}</span>
              <span className="metric-label">总视频数</span>
            </div>
            <div className="metric-card">
              <span className="metric-value">¥{metrics.total_cost?.toFixed(2) ?? "0"}</span>
              <span className="metric-label">总成本</span>
            </div>
            <div className="metric-card">
              <span className="metric-value">{metrics.videos_per_cost_unit?.toFixed(1) ?? "0"}</span>
              <span className="metric-label">每元产出</span>
            </div>
            <div className="metric-card">
              <span className="metric-value">{metrics.remix_multiplier?.toFixed(1) ?? "0"}x</span>
              <span className="metric-label">裂变倍率</span>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
