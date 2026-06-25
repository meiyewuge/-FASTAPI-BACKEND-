/**
 * 工作台 — V4 前端联调版
 * 结构：顶部 → 输入+上传 → 任务状态 → 视频库(含勾选) → 产能
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  generate, aGenerate, bGenerate, compose,
  pollTask, listTasks, listVideos, refreshVideoUrl,
  costSummary, strategies as fetchStrategies, metricsOverview,
  retryTask, exportVideosCSV, exportVideosMp4,
  uploadFile, stableDownload,
  getTenant, clearAuth,
  ENABLE_ADMIN_KEY_FALLBACK,
  type TaskData, type VideoItem, type CostSummary,
  type StrategyItem, type MetricsOverview,
} from "../api/client";

function statusLabel(s: string) {
  const m: Record<string, { text: string; cls: string }> = {
    pending: { text: "排队中", cls: "tag-pending" },
    running: { text: "生成中", cls: "tag-running" },
    done: { text: "已完成", cls: "tag-done" },
    failed: { text: "失败", cls: "tag-failed" },
  };
  const item = m[s] || { text: s, cls: "" };
  return <span className={`tag ${item.cls}`}>{item.text}</span>;
}

export default function Workbench() {
  const navigate = useNavigate();

  // ---- 基础状态 ----
  const [prompt, setPrompt] = useState("");
  const [generating, setGenerating] = useState(false);
  const [tasks, setTasks] = useState<TaskData[]>([]);
  const [activeTask, setActiveTask] = useState<TaskData | null>(null);
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [videoTab, setVideoTab] = useState<"mother" | "viral">("mother");
  const [cost, setCost] = useState<CostSummary | null>(null);
  const [metrics, setMetrics] = useState<MetricsOverview | null>(null);
  const [strats, setStrats] = useState<StrategyItem[]>([]);
  const [selectedStrategy, setSelectedStrategy] = useState("mix");
  const [selectedVideo, setSelectedVideo] = useState<VideoItem | null>(null);
  const [bCount, setBCount] = useState(1);
  const [videoPage, setVideoPage] = useState(1);
  const [videoTotal, setVideoTotal] = useState(0);
  const [toast, setToast] = useState("");
  const [online, setOnline] = useState(navigator.onLine);
  const pollRef = useRef(false);

  // ---- 上传状态 ----
  const [uploadTab, setUploadTab] = useState<"image" | "text" | "video">("image");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadResult, setUploadResult] = useState<{ file_url?: string; file_id?: number; file_name?: string } | null>(null);
  const [textContent, setTextContent] = useState("");

  // ---- 下载状态 ----
  type DLState = "waiting" | "downloading" | "done" | "error";
  const [dlStates, setDlStates] = useState<Record<number, DLState>>({});

  // ---- 导出/勾选 ----
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [exporting, setExporting] = useState(false);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3500); };

  // ---- 网络状态 ----
  useEffect(() => {
    const off = () => setOnline(false);
    const on = () => setOnline(true);
    window.addEventListener("offline", off);
    window.addEventListener("online", on);
    return () => { window.removeEventListener("offline", off); window.removeEventListener("online", on); };
  }, []);

  // ---- 加载 ----
  const loadDashboard = useCallback(async () => {
    const [cR, mR, tR, vR, sR] = await Promise.all([
      costSummary(), metricsOverview(), listTasks(), listVideos("mother", 1, 20), fetchStrategies(),
    ]);
    if (cR.code === 0) setCost(cR.data);
    if (mR.code === 0) setMetrics(mR.data);
    if (tR.code === 0) setTasks(tR.data?.items || []);
    if (vR.code === 0) { setVideos(vR.data?.items || []); setVideoTotal(vR.data?.total || 0); }
    if (sR.code === 0) setStrats(sR.data?.items || []);
  }, []);
  useEffect(() => { loadDashboard(); }, [loadDashboard]);

  const switchVideoTab = async (type: "mother" | "viral") => {
    setVideoTab(type); setVideoPage(1); setSelectedIds(new Set());
    const r = await listVideos(type, 1, 20);
    if (r.code === 0) { setVideos(r.data?.items || []); setVideoTotal(r.data?.total || 0); }
  };
  const loadVideoPage = async (page: number) => {
    setVideoPage(page); setSelectedIds(new Set());
    const r = await listVideos(videoTab, page, 20);
    if (r.code === 0) { setVideos(r.data?.items || []); setVideoTotal(r.data?.total || 0); }
  };

  // ---- 轮询（F3 — 2s）----
  const startPoll = async (taskId: string) => {
    pollRef.current = true;
    const r = await pollTask(taskId, (d) => { if (pollRef.current) setActiveTask({ ...d }); }, 2000);
    pollRef.current = false;
    if (r.code === 0 && r.data) {
      setActiveTask(r.data);
      showToast(r.data.status === "done"
        ? `视频生成完成! 共 ${r.data.result?.videos?.length || 0} 条`
        : "任务失败: " + (r.data.error || "未知原因"));
    } else if (r.code === 4029) { showToast("配额不足"); }
    else if (r.code === -1) { showToast("网络连接中断"); }
    loadDashboard();
  };

  // ---- 生成 ----
  const handleGenerate = async () => {
    if (!prompt.trim()) { showToast("请输入视频需求"); return; }
    setGenerating(true); setActiveTask(null);
    try {
      const r = await generate(prompt.trim());
      if (r.code === 0 && r.data) {
        const ids = r.data.plan?.task_ids || [];
        showToast(`已提交 ${ids.length} 个任务`);
        if (ids.length > 0) startPoll(ids[0]);
      } else showToast(r.message || "生成失败");
    } catch { showToast("网络异常"); } finally { setGenerating(false); }
  };

  const handleAGenerate = async () => {
    if (!prompt.trim()) { showToast("请输入视频需求"); return; }
    setGenerating(true); setActiveTask(null);
    try {
      const r = await aGenerate(prompt.trim());
      if (r.code === 0 && r.data?.task_id) { showToast("A台任务已提交"); startPoll(r.data.task_id); }
      else showToast(r.message || "A台生成失败");
    } catch { showToast("网络异常"); } finally { setGenerating(false); }
  };

  const handleBGenerate = async () => {
    if (!selectedVideo) { showToast("请先选择一条母视频或上传视频素材"); return; }
    setGenerating(true); setActiveTask(null);
    try {
      const r = await bGenerate(selectedVideo.video_id, bCount, selectedStrategy, prompt.trim() || undefined);
      if (r.code === 0 && r.data?.task_id) { showToast(`B台裂变任务已提交（${bCount}条，0元/条）`); startPoll(r.data.task_id); }
      else showToast(r.message || "B台生成失败");
    } catch { showToast("网络异常"); } finally { setGenerating(false); }
  };

  const handleRetry = async (taskId: string) => {
    const r = await retryTask(taskId);
    if (r.code === 0) { showToast("已重新提交"); startPoll(taskId); }
    else showToast(r.message || "重试失败");
  };

  // ---- 上传 ----
  const handleUpload = async (file: File | null) => {
    setUploading(true); setUploadProgress(0); setUploadResult(null);
    const r = await uploadFile(uploadTab, file, undefined, (p) => setUploadProgress(p));
    if (r.code === 0 && r.data) {
      setUploadResult(r.data);
      showToast(`上传成功: ${r.data.file_name}`);
      if (uploadTab === "video") {
        // 视频上传后可作为B台源
        loadDashboard();
      }
    } else {
      showToast(r.message || "上传失败");
    }
    setUploading(false);
  };

  const handleTextUpload = async () => {
    if (!textContent.trim()) { showToast("请输入文本内容"); return; }
    setUploading(true); setUploadProgress(0); setUploadResult(null);
    const r = await uploadFile("text", null, textContent, (p) => setUploadProgress(p));
    if (r.code === 0 && r.data) { setUploadResult(r.data); showToast("脚本上传成功"); }
    else showToast(r.message || "上传失败");
    setUploading(false);
  };

  // ---- 稳定下载（F8 + Task5）----
  const handleSingleDownload = async (v: VideoItem) => {
    if (!v.download_url) return;
    setDlStates((p) => ({ ...p, [v.video_id]: "downloading" }));
    const result = await stableDownload(v, (pct) => {
      // 进度更新（可选）
    });
    setDlStates((p) => ({ ...p, [v.video_id]: result.ok ? "done" : "error" }));
    if (!result.ok) showToast("下载失败: " + result.error);
    setTimeout(() => setDlStates((p) => { const n = { ...p }; delete n[v.video_id]; return n; }), 3000);
  };

  const handleBatchDownload = async (list: VideoItem[]) => {
    const downloadable = list.filter((v) => v.download_url);
    if (!downloadable.length) { showToast("没有可下载的视频"); return; }
    showToast(`开始下载 ${downloadable.length} 个视频...`);
    let okCount = 0;
    for (let i = 0; i < downloadable.length; i++) {
      const v = downloadable[i];
      setDlStates((p) => ({ ...p, [v.video_id]: "downloading" }));
      const r = await stableDownload(v);
      setDlStates((p) => ({ ...p, [v.video_id]: r.ok ? "done" : "error" }));
      if (r.ok) okCount++;
      if (i < downloadable.length - 1) await new Promise((r) => setTimeout(r, 300));
    }
    showToast(`下载完成：${okCount}/${downloadable.length} 成功`);
    setTimeout(() => setDlStates({}), 3000);
  };

  // ---- 导出视频 mp4 ----
  const handleExportMp4 = async () => {
    if (selectedIds.size === 0) { showToast("请先勾选要导出的视频"); return; }
    setExporting(true);
    try {
      const r = await exportVideosMp4({ video_ids: Array.from(selectedIds) });
      if (r.code === 0 && r.data?.videos?.length) {
        showToast(`获取到 ${r.data.videos.length} 个视频URL，开始下载...`);
        const list: VideoItem[] = r.data.videos.map((v) => ({
          ...v, type: "mother" as const, source_video_id: null, share_url: "",
        }));
        await handleBatchDownload(list);
      } else {
        showToast(r.message || "获取视频URL失败");
      }
    } catch { showToast("导出异常"); }
    setExporting(false);
  };

  // ---- 导出 CSV ----
  const handleExportCSV = async () => {
    setExporting(true);
    const ok = await exportVideosCSV({ type: videoTab });
    showToast(ok ? "CSV导出成功" : "导出失败");
    setExporting(false);
  };

  // ---- 勾选 ----
  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };
  const toggleAll = () => {
    if (selectedIds.size === videos.length) setSelectedIds(new Set());
    else setSelectedIds(new Set(videos.map((v) => v.video_id)));
  };

  // ---- 费用预估 ----
  const costPerVideo = metrics && metrics.videos_per_cost_unit > 0 ? 1 / metrics.videos_per_cost_unit : null;
  const parseCount = (t: string) => { const m = t.match(/(\d+)\s*[个条份张]/); return m ? parseInt(m[1], 10) : 1; };
  const batchCount = parseCount(prompt);
  const estimateA = costPerVideo;
  const estimateBatch = estimateA ? estimateA * batchCount : null;
  const overBudget = cost ? (estimateBatch ?? 0) > (cost.remaining ?? 0) : false;

  const resultVideos = activeTask?.result?.videos || [];
  const progressPct = Math.round((activeTask?.progress || 0) * 100);
  const dlBtnText = (id: number) => {
    const s = dlStates[id];
    return s === "downloading" ? "下载中..." : s === "done" ? "已完成" : s === "error" ? "重试" : "下载";
  };
  const dlBtnCls = (id: number) => {
    const s = dlStates[id];
    return `btn btn-sm ${s === "done" ? "btn-done" : s === "error" ? "btn-error" : ""}`;
  };

  return (
    <div className="workbench">
      {toast && <div className="toast">{toast}</div>}
      {!online && <div className="offline-bar">网络连接已断开，请检查网络</div>}

      {/* 1. 顶部 */}
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
              <span className="cost-sub">已用 ¥{cost.spend?.toFixed(2) ?? "0"} / 配额 ¥{cost.quota?.toFixed(2) ?? "0"}</span>
            </div>
          )}
          {ENABLE_ADMIN_KEY_FALLBACK && (
            <button className="btn btn-admin" onClick={() => navigate("/admin")} title="管理员邀约码管理（staging 临时模式）">管理员</button>
          )}
          <button className="btn-logout" onClick={() => { clearAuth(); navigate("/login", { replace: true }); }}>退出</button>
        </div>
      </header>

      {/* 2. 输入区 */}
      <section className="wb-input">
        <textarea className="wb-textarea" placeholder="请输入视频需求，例如：帮我做10个广州美容院抗衰视频"
          value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} disabled={generating} />
        <div className="wb-actions">
          <button className="btn btn-primary" onClick={handleGenerate} disabled={generating || !online}>
            {generating ? "提交中..." : "⚡ 一句话批量生成"}
          </button>
          <button className="btn btn-a" onClick={handleAGenerate} disabled={generating || !online}
            title="A台调用火山引擎，会产生AI费用">🎬 A台·母视频（⚠️会产生费用）</button>
          <button className="btn btn-b" onClick={handleBGenerate} disabled={generating || !selectedVideo || !online}
            title={!selectedVideo ? "请先选择母视频或上传视频" : "B台本地ffmpeg裂变，0 AI成本"}>🔁 B台·裂变（0元/条）</button>
        </div>
        {costPerVideo && prompt.trim() && (
          <div className={`cost-estimate ${overBudget ? "cost-over-budget" : ""}`}>
            <span className="cost-estimate-label">预估费用：</span>
            {batchCount > 1 ? <span>批量{batchCount}条 ≈ <strong>¥{estimateBatch!.toFixed(2)}</strong></span>
              : <span>A台单条 ≈ <strong>¥{estimateA!.toFixed(2)}</strong></span>}
            <span className="cost-estimate-sep">|</span>
            <span>B台裂变 = <strong>0元/条</strong>（本地ffmpeg）</span>
            <span className="cost-estimate-sep">|</span>
            <span className="cost-estimate-remaining">剩余 ¥{cost?.remaining?.toFixed(2) ?? "--"}</span>
            {overBudget && <span className="cost-over-warn">⚠️ 超出剩余额度</span>}
          </div>
        )}
      </section>

      {/* 3. 上传素材 */}
      <section className="wb-upload">
        <h2>上传素材</h2>
        <div className="upload-tabs">
          <button className={uploadTab === "image" ? "tab active" : "tab"} onClick={() => setUploadTab("image")}>图片</button>
          <button className={uploadTab === "text" ? "tab active" : "tab"} onClick={() => setUploadTab("text")}>文字/脚本</button>
          <button className={uploadTab === "video" ? "tab active" : "tab"} onClick={() => setUploadTab("video")}>视频</button>
        </div>
        <div className="upload-area">
          {uploadTab === "text" ? (
            <div className="upload-text">
              <textarea className="wb-textarea" placeholder="输入脚本/分镜文案..." value={textContent}
                onChange={(e) => setTextContent(e.target.value)} rows={4} />
              <button className="btn btn-sm" onClick={handleTextUpload} disabled={uploading}>
                {uploading ? `上传中 ${uploadProgress}%` : "上传文本"}
              </button>
            </div>
          ) : (
            <div className="upload-file-area" onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleUpload(f); }}>
              <input type="file" id="fileInput" className="upload-file-input"
                accept={uploadTab === "image" ? ".jpg,.png,.webp" : ".mp4,.mov,.avi"}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) handleUpload(f); }} />
              <label htmlFor="fileInput" className="upload-drop-zone">
                <p>{uploadTab === "image" ? "点击或拖拽上传图片（jpg/png/webp，≤10MB）" : "点击或拖拽上传视频（mp4/mov/avi，≤500MB）"}</p>
              </label>
              {uploading && (
                <div className="upload-progress">
                  <div className="progress-bar"><div className="progress-fill" style={{ width: `${uploadProgress}%` }} /></div>
                  <span>{uploadProgress}%</span>
                </div>
              )}
            </div>
          )}
          {uploadResult && (
            <div className="upload-result">
              <span>上传成功: {uploadResult.file_name || `#${uploadResult.file_id}`}</span>
              {uploadResult.file_url && <a href={uploadResult.file_url} target="_blank" rel="noreferrer">查看</a>}
            </div>
          )}
        </div>
      </section>

      {/* 4. 任务状态 */}
      <section className="wb-tasks">
        <h2>任务状态</h2>
        {activeTask && (
          <div className="active-task">
            <div className="task-header">
              <span className="task-id">{activeTask.task_id.slice(0, 8)}</span>
              <span className="task-type-badge">{activeTask.type === "a" ? "A台·母视频" : "B台·裂变"}</span>
              {statusLabel(activeTask.status)}
            </div>
            {activeTask.status === "running" && (
              <div className="progress-section">
                <div className="progress-bar"><div className="progress-fill" style={{ width: `${progressPct}%` }} /></div>
                <span className="progress-text">{progressPct}%</span>
              </div>
            )}
            {activeTask.status === "pending" && <p className="task-hint">任务排队中...</p>}
            {activeTask.error && (
              <div className="task-error">
                <span>{activeTask.error}</span>
                <button className="btn btn-sm" onClick={() => handleRetry(activeTask.task_id)}>重试</button>
              </div>
            )}
          </div>
        )}
        {resultVideos.length > 0 && (
          <div className="result-videos">
            <div className="result-header">
              <h3>生成结果（{resultVideos.length} 条）</h3>
              {resultVideos.some((v) => v.download_url) && (
                <button className="btn btn-download-all" onClick={() => handleBatchDownload(resultVideos)}>
                  📥 全部下载（{resultVideos.filter((v) => v.download_url).length}）
                </button>
              )}
            </div>
            <div className="video-grid">
              {resultVideos.map((v, i) => (
                <div key={v.video_id || i} className="video-card">
                  <div className="video-preview">
                    {v.download_url ? <video src={v.download_url} controls preload="metadata" />
                      : <div className="video-placeholder">视频加载中</div>}
                  </div>
                  <div className="video-info">
                    <span className="video-type-badge">{v.type === "mother" ? "母视频" : "裂变"}</span>
                    {v.strategy && <span className="video-strategy">{v.strategy}</span>}
                    <span className="video-id">#{v.video_id || `tmp-${i}`}</span>
                    <div className="video-actions">
                      {v.download_url && (
                        <button className={dlBtnCls(v.video_id)} onClick={() => handleSingleDownload(v)}
                          disabled={dlStates[v.video_id] === "downloading"}>{dlBtnText(v.video_id)}</button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        {tasks.length > 0 && (
          <div className="task-list">
            <h3>近期任务</h3>
            <table className="task-table">
              <thead><tr><th>编号</th><th>类型</th><th>状态</th><th>进度</th><th>操作</th></tr></thead>
              <tbody>
                {tasks.slice(0, 10).map((t) => (
                  <tr key={t.task_id} className={activeTask?.task_id === t.task_id ? "active-row" : ""}
                    onClick={() => setActiveTask(t)}>
                    <td>{t.task_id.slice(0, 8)}</td>
                    <td>{t.type === "a" ? "A台" : "B台"}</td>
                    <td>{statusLabel(t.status)}</td>
                    <td>{Math.round((t.progress || 0) * 100)}%</td>
                    <td>{t.status === "failed" && <button className="btn btn-sm"
                      onClick={(e) => { e.stopPropagation(); handleRetry(t.task_id); }}>重试</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* 5. 视频库 + 勾选 + 导出 */}
      <section className="wb-videos">
        <div className="video-section-header">
          <h2>视频库</h2>
          <div className="video-section-actions">
            <div className="video-tabs">
              <button className={videoTab === "mother" ? "tab active" : "tab"} onClick={() => switchVideoTab("mother")}>母视频</button>
              <button className={videoTab === "viral" ? "tab active" : "tab"} onClick={() => switchVideoTab("viral")}>裂变视频</button>
            </div>
            <button className="btn btn-export" onClick={handleExportCSV} disabled={exporting || !videos.length}>
              {exporting ? "导出中..." : "📄 导出CSV"}
            </button>
            <button className="btn btn-export-mp4" onClick={handleExportMp4} disabled={exporting || selectedIds.size === 0}>
              📥 导出视频（{selectedIds.size}）
            </button>
          </div>
        </div>
        {/* B台策略 */}
        {selectedVideo && strats.length > 0 && (
          <div className="strategy-bar">
            <span>裂变策略：</span>
            {strats.map((s) => (
              <button key={s.key} className={selectedStrategy === s.key ? "strat-btn active" : "strat-btn"}
                onClick={() => setSelectedStrategy(s.key)} title={s.goal}>{s.label}</button>
            ))}
            <span className="bcount-control">
              数量：<input type="number" min={1} max={50} value={bCount}
                onChange={(e) => setBCount(Math.max(1, Math.min(50, parseInt(e.target.value) || 1)))}
                className="bcount-input" />
              条
            </span>
          </div>
        )}
        {selectedVideo && (
          <p className="selected-hint">
            已选：{selectedVideo.title || `#${selectedVideo.video_id}`}
            <button className="btn-text" onClick={() => setSelectedVideo(null)}>取消</button>
          </p>
        )}
        {videos.length === 0 ? (
          <div className="empty-state">暂无{videoTab === "mother" ? "母视频" : "裂变视频"}记录</div>
        ) : (
          <>
            <div className="select-bar">
              <button className="btn btn-sm" onClick={toggleAll}>
                {selectedIds.size === videos.length ? "取消全选" : "全选"}
              </button>
              <span>已选 {selectedIds.size} 条</span>
            </div>
            <div className="video-grid">
              {videos.map((v) => (
                <div key={v.video_id} className={`video-card ${selectedVideo?.video_id === v.video_id ? "selected" : ""} ${selectedIds.has(v.video_id) ? "checked" : ""}`}>
                  <div className="video-checkbox" onClick={(e) => { e.stopPropagation(); toggleSelect(v.video_id); }}>
                    <input type="checkbox" checked={selectedIds.has(v.video_id)} readOnly />
                  </div>
                  <div className="video-preview" onClick={() => setSelectedVideo(selectedVideo?.video_id === v.video_id ? null : v)}>
                    {v.download_url ? <video src={v.download_url} controls preload="metadata" />
                      : <div className="video-placeholder">{v.title || "视频"}</div>}
                  </div>
                  <div className="video-info" onClick={() => setSelectedVideo(selectedVideo?.video_id === v.video_id ? null : v)}>
                    <span className="video-title">{v.title || `视频 #${v.video_id}`}</span>
                    <div className="video-actions">
                      {videoTab === "mother" && (
                        <button className={`btn btn-sm ${selectedVideo?.video_id === v.video_id ? "btn-selected" : "btn-b-split"}`}
                          onClick={(e) => { e.stopPropagation(); setSelectedVideo(selectedVideo?.video_id === v.video_id ? null : v); }}
                          title="选择此视频作为B台裂变源">
                          {selectedVideo?.video_id === v.video_id ? "✓ 已选" : "🔁 用此裂变"}
                        </button>
                      )}
                      {v.download_url && (
                        <button className={dlBtnCls(v.video_id)} onClick={(e) => { e.stopPropagation(); handleSingleDownload(v); }}
                          disabled={dlStates[v.video_id] === "downloading"}>{dlBtnText(v.video_id)}</button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
            {videoTotal > 20 && (
              <div className="pagination">
                <button disabled={videoPage <= 1} onClick={() => loadVideoPage(videoPage - 1)}>上一页</button>
                <span>{videoPage} / {Math.ceil(videoTotal / 20)}</span>
                <button disabled={videoPage >= Math.ceil(videoTotal / 20)} onClick={() => loadVideoPage(videoPage + 1)}>下一页</button>
              </div>
            )}
          </>
        )}
      </section>

      {/* 6. 产能 */}
      {metrics && (
        <section className="wb-metrics">
          <h2>产能概览</h2>
          <div className="metrics-grid">
            <div className="metric-card"><span className="metric-value">{metrics.total_videos ?? 0}</span><span className="metric-label">总视频数</span></div>
            <div className="metric-card"><span className="metric-value">¥{metrics.total_cost?.toFixed(2) ?? "0"}</span><span className="metric-label">总成本</span></div>
            <div className="metric-card"><span className="metric-value">{metrics.videos_per_cost_unit?.toFixed(1) ?? "0"}</span><span className="metric-label">每元产出</span></div>
            <div className="metric-card"><span className="metric-value">{metrics.remix_multiplier?.toFixed(1) ?? "0"}x</span><span className="metric-label">裂变倍率</span></div>
          </div>
        </section>
      )}
    </div>
  );
}
