/**
 * 工作台 — V4 P1 单框工作流（Manus 风格）
 * 三区块：操作对话框 → 母视频/源视频陈列面 → 裂变视频陈列面
 *
 * P1 核心改动：
 *  - current_source_video_ids 会话源池（上传/A台产出自动加入）
 *  - B台按钮读 duration_seconds >= 30 硬门槛（≥3 合格源才可用）
 *  - A台主入口 POST /api/compose + 费用确认弹窗
 *  - B台 P1 标准请求体 source_video_ids + auto_ratio + max_outputs
 *  - 删除：文本入口、蓝色上传素材按钮、勾选确认流程
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  listVideos, refreshVideoUrl, stableDownload, costSummary,
  strategies as fetchStrategies, batchUpload,
  batchGenerate, pollBatchStatus, deleteVideo, storageStatus,
  trackEvent, videoFeedback, compose, pollTask,
  getTenant, clearAuth, getToken,
  isAdmin, isSuperAdmin, getUserProfile, fetchMe,
  type VideoItem, type CostSummary, type StrategyItem,
  type BatchStatus, type StorageStatus, type TaskData,
} from "../api/client";

function fmtDuration(s?: number | null) {
  if (s == null) return "时长未知";
  const m = Math.floor(s / 60), sec = Math.round(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}
function fmtSize(bytes?: number) {
  if (!bytes) return "-";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

// ====================== 上传文件本地类型 ======================
interface LocalFile {
  id: string;
  file: File;
  type: "image" | "video" | "file";
  status: "pending" | "uploading" | "ok" | "failed";
  progress?: number;
  fileUrl?: string;
  fileId?: number;
  videoId?: number;
  error?: string;
}

export default function Workbench() {
  const navigate = useNavigate();

  // ---- 基础状态 ----
  const [prompt, setPrompt] = useState("");
  const [toast, setToast] = useState("");
  const [online, setOnline] = useState(navigator.onLine);
  const [cost, setCost] = useState<CostSummary | null>(null);
  const [strats, setStrats] = useState<StrategyItem[]>([]);
  const [storage, setStorage] = useState<StorageStatus | null>(null);

  // ---- 上传状态 ----
  const [localFiles, setLocalFiles] = useState<LocalFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  // ---- 母视频 / 源视频 ----
  const [motherVideos, setMotherVideos] = useState<VideoItem[]>([]);
  const [motherTotal, setMotherTotal] = useState(0);
  const [motherPage, setMotherPage] = useState(1);

  // ---- 裂变视频 ----
  const [viralVideos, setViralVideos] = useState<VideoItem[]>([]);
  const [viralTotal, setViralTotal] = useState(0);
  const [viralPage, setViralPage] = useState(1);

  // ---- P1: 本次会话源视频池 ----
  const [currentSourceVideoIds, setCurrentSourceVideoIds] = useState<number[]>([]);

  // ---- P1: A台 compose 状态 ----
  const [composeRunning, setComposeRunning] = useState(false);
  const [composeProgress, setComposeProgress] = useState("");

  // ---- P1: B台裂变状态 ----
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null);
  const [batchIgnored, setBatchIgnored] = useState<number[]>([]);
  const batchPollRef = useRef(false);

  // ---- 反馈弹出菜单 ----
  const [feedbackOpen, setFeedbackOpen] = useState<number | null>(null);

  // ---- 下载状态 ----
  type DLState = "waiting" | "downloading" | "done" | "error";
  const [dlStates, setDlStates] = useState<Record<number, DLState>>({});

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3500); };
  const PAGE_SIZE = 50;
  const viralRef = useRef<HTMLElement>(null);

  // ---- P1: 合格源视频计算（duration_seconds >= 30） ----
  const qualifiedSources = currentSourceVideoIds.filter(id => {
    const v = motherVideos.find(m => m.video_id === id);
    return v && v.duration_seconds != null && v.duration_seconds >= 30;
  });
  const qualifiedCount = qualifiedSources.length;
  const estimatedOutputs = qualifiedCount >= 5 ? 50 : qualifiedCount * 10;
  const bEnabled = qualifiedCount >= 3 && !batchRunning && !composeRunning;

  // ---- 网络状态 ----
  useEffect(() => {
    const off = () => setOnline(false);
    const on = () => setOnline(true);
    window.addEventListener("offline", off);
    window.addEventListener("online", on);
    return () => { window.removeEventListener("offline", off); window.removeEventListener("online", on); };
  }, []);

  useEffect(() => {
    if (!getUserProfile() && getToken()) fetchMe();
  }, []);

  // ---- 加载仪表盘 ----
  const loadDashboard = useCallback(async () => {
    const [cR, sR, stR] = await Promise.all([costSummary(), fetchStrategies(), storageStatus()]);
    if (cR.code === 0) setCost(cR.data);
    if (sR.code === 0) setStrats(sR.data?.items || []);
    if (stR.code === 0) setStorage(stR.data);
  }, []);
  useEffect(() => { loadDashboard(); }, [loadDashboard]);

  const loadMother = useCallback(async (p = 1) => {
    const r = await listVideos("mother", p, PAGE_SIZE);
    if (r.code === 0) { setMotherVideos(r.data?.items || []); setMotherTotal(r.data?.total || 0); }
  }, []);

  const loadViral = useCallback(async (p = 1, batchId?: string) => {
    const r = await listVideos("viral", p, PAGE_SIZE, batchId);
    if (r.code === 0) { setViralVideos(r.data?.items || []); setViralTotal(r.data?.total || 0); }
  }, []);

  useEffect(() => { loadMother(motherPage); }, [motherPage, loadMother]);
  useEffect(() => { loadViral(viralPage); }, [viralPage, loadViral]);

  // ===================== 上传处理（自动上传，无蓝色按钮）=====================
  const handleFilesSelected = async (files: FileList | null, type: "image" | "video" | "file") => {
    if (!files) return;
    const maxCounts = { image: 10, video: 10, file: 10 };
    const current = localFiles.filter(f => f.type === type);
    const remaining = maxCounts[type] - current.length;
    if (remaining <= 0) { showToast(`${type === "image" ? "图片" : type === "video" ? "视频" : "文件"}已达上限 ${maxCounts[type]} 个`); return; }

    const arr = Array.from(files).slice(0, remaining);
    const newFiles: LocalFile[] = arr.map((f, i) => ({
      id: `${Date.now()}-${i}`, file: f, type, status: "pending" as const,
    }));
    setLocalFiles(prev => [...prev, ...newFiles]);
    // P1: 自动上传
    await doUpload([...newFiles], type);
  };

  const removeLocalFile = (id: string) => {
    setLocalFiles(prev => prev.filter(f => f.id !== id));
  };

  const doUpload = async (files: LocalFile[], type: "image" | "video" | "file") => {
    setUploading(true);
    setUploadProgress(0);
    const fileObjs = files.map(f => f.file);

    setLocalFiles(prev => prev.map(f => files.find(x => x.id === f.id) ? { ...f, status: "uploading" as const } : f));
    const r = await batchUpload(fileObjs, type, (pct) => setUploadProgress(pct));

    if (r.code === 0 && r.data) {
      const uploaded = r.data.uploaded || [];
      const failed = r.data.failed || [];

      // P1: 上传视频成功 → 把 video_id 加入 current_source_video_ids
      if (type === "video") {
        const newIds = uploaded.filter(u => u.video_id != null).map(u => u.video_id!);
        if (newIds.length > 0) {
          setCurrentSourceVideoIds(prev => [...prev, ...newIds]);
        }
      }

      setLocalFiles(prev => prev.map(f => {
        const match = files.find(x => x.id === f.id);
        if (!match) return f;
        const idx = files.indexOf(match);
        const item = uploaded[idx];
        const failItem = failed.find(fl => fl.file_name === f.file.name);
        if (item && item.status !== "failed") {
          return { ...f, status: "ok" as const, fileUrl: item.file_url, fileId: item.file_id, videoId: item.video_id || undefined };
        }
        return { ...f, status: "failed" as const, error: failItem?.reason || item?.status || "上传失败" };
      }));

      if (failed.length > 0) showToast(`${failed.length} 个文件上传失败`);
      else showToast(`素材上传完成`);
    } else {
      setLocalFiles(prev => prev.map(f => files.find(x => x.id === f.id) ? { ...f, status: "failed" as const, error: r.message } : f));
      showToast(r.message || "上传失败");
    }
    setUploading(false);
    setUploadProgress(100);
    loadMother(1);
    loadDashboard();
  };

  // ===================== A台 compose（P1 主入口）=====================
  const handleAConfirm = async () => {
    if (!prompt.trim()) { showToast("请先描述需求"); return; }
    setComposeRunning(true);
    setComposeProgress("正在提交生成任务…");
    trackEvent("send_to_a", { prompt: prompt.slice(0, 50) });

    const r = await compose(prompt, 60, "1080p");
    if (r.code === 0 && r.data?.task_id) {
      setComposeProgress("正在生成母视频…");
      pollTask(r.data.task_id, (d: TaskData) => {
        if (d.status === "running") setComposeProgress(`正在生成中… (${Math.round((d.progress || 0) * 100)}%)`);
        if (d.status === "done") setComposeProgress("正在拼接…");
      }).then((final) => {
        setComposeRunning(false);
        setComposeProgress("");
        if (final.data?.status === "done") {
          // P1: A台生成母视频后 → 把新 video_id 加入 current_source_video_ids
          const resultVideos = final.data.result?.videos || [];
          const newIds = resultVideos.filter(v => v.video_id).map(v => v.video_id);
          if (newIds.length > 0) setCurrentSourceVideoIds(prev => [...prev, ...newIds]);
          showToast("母视频已生成");
          loadMother(1);
          loadDashboard();
        } else {
          const errMsg = final.data?.error || final.message || "生成失败";
          if (final.code === 4029) showToast("余额不足，请联系管理员充值");
          else showToast(errMsg);
        }
      });
    } else {
      setComposeRunning(false);
      setComposeProgress("");
      if (r.code === 4029) showToast("余额不足，请联系管理员充值");
      else showToast(r.message || "提交生成失败");
    }
  };

  // ===================== B台裂变（P1 自动选源 + 1:10）=====================
  const handleBClick = async () => {
    if (qualifiedCount < 3) {
      // 门槛不足弹窗
      const maxDuration = motherVideos.reduce((max, v) => {
        const d = v.duration_seconds;
        return d != null && d > max ? d : max;
      }, 0);
      showToast(`暂无法裂变。请至少上传3个时长30秒以上的视频。当前：${currentSourceVideoIds.length}个视频，最长${Math.round(maxDuration)}秒`);
      return;
    }

    const sourceIds = qualifiedSources.slice(0, 5); // 最多取前5个
    const totalOutputs = sourceIds.length * 10;
    setBatchRunning(true);
    setBatchStatus(null);
    setBatchIgnored([]);
    trackEvent("send_to_b", { source_ids: sourceIds });

    const r = await batchGenerate(sourceIds, prompt || undefined);
    if (r.code === 0 && r.data) {
      const { batch_id, ignored_source_video_ids } = r.data;
      if (ignored_source_video_ids && ignored_source_video_ids.length > 0) {
        setBatchIgnored(ignored_source_video_ids);
        showToast(`本次仅使用前5个合格源视频，${ignored_source_video_ids.length}个未参与`);
      }
      showToast(`裂变任务已提交，正在裂变…`);
      batchPollRef.current = true;

      pollBatchStatus(batch_id, (d) => {
        setBatchStatus(d);
      }).then((final) => {
        batchPollRef.current = false;
        setBatchRunning(false);
        if (final.data?.status === "done") {
          const completed = final.data.completed || 0;
          const failed = final.data.failed || 0;
          showToast(failed > 0 ? `部分裂变失败，已成功 ${completed} 条` : `裂变完成！产出 ${completed} 条`);
          // P1: 刷新裂变陈列面 + 自动滚动
          loadViral(1, batch_id);
          loadDashboard();
          setTimeout(() => {
            viralRef.current?.scrollIntoView({ behavior: "smooth" });
          }, 300);
        } else {
          showToast(`裂变任务结束: ${final.data?.status || "未知状态"}`);
        }
      });
    } else {
      setBatchRunning(false);
      showToast(r.message || "提交裂变失败");
    }
  };

  // ===================== 视频操作 =====================
  const handlePlay = (v: VideoItem) => {
    trackEvent("play", { video_id: v.video_id });
    if (v.download_url) window.open(v.download_url, "_blank");
    else if (v.share_url) window.open(v.share_url, "_blank");
  };

  const handleDownload = async (v: VideoItem) => {
    if (!v.download_url) { showToast("暂无下载链接"); return; }
    trackEvent("download", { video_id: v.video_id });
    setDlStates(p => ({ ...p, [v.video_id]: "downloading" }));
    const r = await stableDownload(v);
    setDlStates(p => ({ ...p, [v.video_id]: r.ok ? "done" : "error" }));
    if (!r.ok) showToast(r.error || "下载失败");
    setTimeout(() => setDlStates(p => { const n = { ...p }; delete n[v.video_id]; return n; }), 3000);
  };

  const handleDelete = async (v: VideoItem) => {
    if (!confirm(`确认删除视频 #${v.video_id}？此操作不可恢复。`)) return;
    const r = await deleteVideo(v.video_id);
    if (r.code === 0) {
      trackEvent("delete", { video_id: v.video_id });
      showToast(`视频 #${v.video_id} 已删除`);
      if (v.type === "viral") loadViral(viralPage);
      else loadMother(motherPage);
      loadDashboard();
      // 从 current_source_video_ids 中移除
      setCurrentSourceVideoIds(prev => prev.filter(id => id !== v.video_id));
    } else {
      showToast(r.code === 403 ? "无权删除其他租户的视频" : (r.message || "删除失败"));
    }
  };

  const handleFeedback = async (videoId: number, rating: "good" | "bad") => {
    setFeedbackOpen(null);
    const note = rating === "bad" ? (window.prompt("输入备注（可选）:") || undefined) : undefined;
    const r = await videoFeedback(videoId, rating, undefined, note);
    if (r.code === 0) showToast("加入候选池，待审核");
    else showToast(r.message || "反馈提交失败，请重试");
  };

  // ===================== 汇总统计 =====================
  const imageFiles = localFiles.filter(f => f.type === "image");
  const videoFiles = localFiles.filter(f => f.type === "video");
  const docFiles = localFiles.filter(f => f.type === "file");
  const hasUploads = localFiles.length > 0;

  const dlBtnText = (id: number) => {
    const s = dlStates[id];
    return s === "downloading" ? "下载中..." : s === "done" ? "✓" : s === "error" ? "重试" : "下载";
  };

  // ===================== RENDER =====================
  return (
    <div className="wf-page">
      {toast && <div className="toast">{toast}</div>}
      {!online && <div className="offline-bar">网络连接已断开，请检查网络</div>}

      {/* ===== Header ===== */}
      <header className="wf-header">
        <div className="wf-header-left">
          <h1>美业AI视频系统</h1>
          <span className="tenant-badge">租户: {getTenant()}</span>
        </div>
        <div className="wf-header-right">
          {cost && (
            <div className="cost-panel">
              <span className="cost-label">剩余额度</span>
              <span className="cost-value">¥{cost.remaining?.toFixed(2) ?? "--"}</span>
              <span className="cost-sub">已用 ¥{cost.spend?.toFixed(2) ?? "0"} / 配额 ¥{cost.quota?.toFixed(2) ?? "0"}</span>
            </div>
          )}
          {isAdmin() && (
            <button className="btn btn-admin" onClick={() => navigate("/admin")} title="管理员后台">管理员</button>
          )}
          <button className="btn-logout" onClick={() => { clearAuth(); navigate("/login", { replace: true }); }}>退出</button>
        </div>
      </header>

      {/* ===== 存储状态条 ===== */}
      {storage && (
        <div className="storage-bar">
          <strong>存储:</strong>
          <span>母视频 {storage.mother_count}</span>
          <span>裂变 {storage.viral_count}</span>
          <span>上传 {storage.upload_count}</span>
          <span>占用 {storage.estimated_used_mb?.toFixed(1)} MB</span>
          {isSuperAdmin() && storage.disk_used_percent != null && (
            <span>磁盘 {storage.disk_used_percent.toFixed(1)}%</span>
          )}
        </div>
      )}

      {/* ===== 区块一：操作对话框 ===== */}
      <section className="wf-dialog">
        <h2>我能为你做什么？</h2>
        <textarea
          className="wf-prompt"
          placeholder="描述你的需求，上传素材，开始创作…"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
        />

        {/* P1: 上传区（图片/文件/视频，无文本入口） */}
        <div className="upload-zone">
          <label className="upload-btn">
            🖼️ 图片
            <input type="file" accept=".jpg,.jpeg,.png,.webp" multiple
              onChange={(e) => { handleFilesSelected(e.target.files, "image"); e.target.value = ""; }} />
          </label>
          <label className="upload-btn">
            📁 文件
            <input type="file" accept=".doc,.docx,.zip" multiple
              onChange={(e) => { handleFilesSelected(e.target.files, "file"); e.target.value = ""; }} />
          </label>
          <label className="upload-btn">
            🎬 视频
            <input type="file" accept=".mp4,.mov,.avi" multiple
              onChange={(e) => { handleFilesSelected(e.target.files, "video"); e.target.value = ""; }} />
          </label>
        </div>

        {/* 素材汇总条 */}
        {hasUploads && (
          <div className="upload-summary">
            {imageFiles.length > 0 && <span className="upload-summary-item">🖼️ 图片 x{imageFiles.length}</span>}
            {docFiles.length > 0 && <><span className="upload-summary-sep">/</span><span className="upload-summary-item">📁 文件 x{docFiles.length}</span></>}
            {videoFiles.length > 0 && <><span className="upload-summary-sep">/</span><span className="upload-summary-item">🎬 视频 x{videoFiles.length}</span></>}
            <span className="upload-summary-link" onClick={() => setLocalFiles([])}>清除全部</span>
          </div>
        )}

        {/* 上传缩略图 */}
        {localFiles.length > 0 && (
          <div className="upload-thumbs">
            {localFiles.map(f => (
              <div key={f.id} className="upload-thumb">
                {f.type === "image" ? (
                  <img src={URL.createObjectURL(f.file)} alt={f.file.name} />
                ) : f.type === "video" ? (
                  <video src={URL.createObjectURL(f.file)} muted />
                ) : (
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", fontSize: 11, color: "#64748b", padding: 4, textAlign: "center" }}>
                    {f.file.name}
                  </div>
                )}
                <span className="thumb-name">{f.file.name}</span>
                <button className="thumb-remove" onClick={(e) => { e.stopPropagation(); removeLocalFile(f.id); }}>✕</button>
                {f.status === "failed" && <div className="thumb-fail">{f.error || "失败"}</div>}
              </div>
            ))}
          </div>
        )}

        {/* 上传进度 */}
        {uploading && (
          <div className="upload-progress-bar">
            <div className="upload-progress-fill" style={{ width: `${uploadProgress}%` }} />
          </div>
        )}

        {/* P1: 操作按钮（仅 A台 + B台，无蓝色上传素材按钮） */}
        <div className="action-bar">
          <button className="btn btn-a" onClick={handleAConfirm}
            disabled={composeRunning || batchRunning || !online || !prompt.trim()}
            title={prompt.trim() ? "A台母视频生成，会产生费用" : "请先描述需求"}>
            🎬 A台·母视频（⚠️会产生费用）
          </button>
          <button className="btn btn-b" onClick={handleBClick}
            disabled={!bEnabled || !online}
            title={qualifiedCount >= 3 ? `B台裂变 0 元/条，预计 ${estimatedOutputs} 条` : "请至少上传3个时长30秒以上的视频"}>
            🔁 B台·裂变（0 元/条）
            {qualifiedCount > 0 && <small style={{ display: "block", fontSize: 11, opacity: 0.9 }}>
              {qualifiedCount >= 3 ? `合格源 ${qualifiedCount} 个 → 预计 ${estimatedOutputs} 条` :
                `合格源 ${qualifiedCount}/3 个（需30秒以上）`}
            </small>}
          </button>
        </div>

        {/* P1: 裂变进度条 */}
        {batchRunning && batchStatus && (
          <div className="batch-progress">
            <div className="batch-progress-header">
              <span>正在裂变…</span>
              <span>{batchStatus.completed} / {batchStatus.total_outputs}</span>
            </div>
            <div className="progress-bar">
              <div className="progress-fill" style={{
                width: `${batchStatus.total_outputs > 0 ? (batchStatus.completed / batchStatus.total_outputs * 100) : 0}%`
              }} />
            </div>
          </div>
        )}
        {batchRunning && !batchStatus && (
          <div className="batch-progress">
            <div className="batch-progress-header"><span>正在提交裂变任务…</span></div>
            <div className="progress-bar"><div className="progress-fill" style={{ width: "10%", animation: "load 1.4s infinite" }} /></div>
          </div>
        )}

        {/* P1: A台生成进度 */}
        {composeRunning && (
          <div className="batch-progress">
            <div className="batch-progress-header"><span>{composeProgress}</span></div>
            <div className="progress-bar"><div className="progress-fill" style={{ width: "40%", animation: "load 1.4s infinite" }} /></div>
          </div>
        )}

        {/* P1: 源视频池状态（辅助信息） */}
        {currentSourceVideoIds.length > 0 && (
          <div style={{ marginTop: 10, fontSize: 12, color: "#64748b" }}>
            会话源视频池: {currentSourceVideoIds.length} 个（合格 {qualifiedCount} 个）
            {qualifiedCount >= 5 && <span> · 本轮最多使用前5个合格视频，预计生成50条</span>}
            {batchIgnored.length > 0 && <span style={{ color: "#f59e0b" }}> · 部分视频未参与本轮裂变，本轮最多使用5个合格源视频</span>}
          </div>
        )}
      </section>

      {/* ===== 区块二：母视频 / 源视频陈列面 ===== */}
      <section className="video-gallery">
        <div className="gallery-header">
          <h3>母视频 / 源视频<span className="gallery-count">({motherTotal})</span></h3>
        </div>

        {motherVideos.length === 0 ? (
          <div className="empty-state">还没有母视频，上传视频或使用A台生成</div>
        ) : (
          <div className="video-grid">
            {motherVideos.map(v => (
              <div key={v.video_id} className="video-card">
                <div className="video-preview" onClick={() => handlePlay(v)}>
                  {v.cover_url ? <img className="video-cover" src={v.cover_url} alt="" /> :
                    v.download_url ? <video src={v.download_url} muted /> :
                      <span className="video-placeholder">暂无预览</span>}
                  <span className={`video-source-badge ${v.source_type === "uploaded" || v.source === "upload" ? "source-upload" : "source-a"}`}>
                    {v.source_type === "uploaded" || v.source === "upload" ? "本地上传" : "A台生成"}
                  </span>
                </div>
                <div className="video-info">
                  <div className="video-title">{v.title || `视频 #${v.video_id}`}</div>
                  <div className="video-meta">
                    <span className="video-id">#{v.video_id}</span>
                    <span>{v.duration_seconds != null ? fmtDuration(v.duration_seconds) :
                      <span style={{ color: "#f59e0b" }} title="需重新上传或等待解析">时长未知</span>}</span>
                    {v.file_size != null && <span>{fmtSize(v.file_size)}</span>}
                    {v.created_at && <span>{new Date(v.created_at).toLocaleDateString("zh-CN")}</span>}
                  </div>
                </div>
                <div className="video-actions">
                  <button className="btn btn-sm" onClick={() => handlePlay(v)}>播放</button>
                  <button className="btn btn-sm" onClick={() => handleDownload(v)}
                    title="浏览器将保存到你的电脑下载目录">{dlBtnText(v.video_id)}</button>
                  <button className="btn btn-sm btn-error" onClick={() => handleDelete(v)}>删除</button>
                </div>
              </div>
            ))}
          </div>
        )}
        {motherTotal > PAGE_SIZE && (
          <div className="pagination">
            <button disabled={motherPage <= 1} onClick={() => setMotherPage(p => p - 1)}>上一页</button>
            <span>第 {motherPage} 页 / 共 {Math.ceil(motherTotal / PAGE_SIZE)} 页</span>
            <button disabled={motherPage * PAGE_SIZE >= motherTotal} onClick={() => setMotherPage(p => p + 1)}>下一页</button>
          </div>
        )}
      </section>

      {/* ===== 区块三：裂变视频陈列面 ===== */}
      <section className="video-gallery" ref={viralRef as React.RefObject<HTMLDivElement>}>
        <div className="gallery-header">
          <h3>裂变视频<span className="gallery-count">({viralTotal})</span></h3>
        </div>

        <div className="viral-notice">
          ⏰ 裂变视频服务器临时保留 5 天，请及时下载到本地。B台裂变 0 元。
        </div>

        {viralVideos.length === 0 ? (
          <div className="empty-state">还没有裂变视频，上传3个以上源视频后使用B台裂变</div>
        ) : (
          <div className="video-grid">
            {viralVideos.map(v => (
              <div key={v.video_id} className="video-card">
                <div className="video-preview" onClick={() => handlePlay(v)}>
                  {v.cover_url ? <img className="video-cover" src={v.cover_url} alt="" /> :
                    v.download_url ? <video src={v.download_url} muted /> :
                      <span className="video-placeholder">暂无预览</span>}
                  <span className="video-source-badge source-b">B台裂变</span>
                </div>
                <div className="video-info">
                  <div className="video-title">{v.title || `裂变 #${v.video_id}`}</div>
                  <div className="video-meta">
                    <span className="video-id">#{v.video_id}</span>
                    {v.source_video_id && <span>源: #{v.source_video_id}</span>}
                    <span>{v.duration_seconds != null ? fmtDuration(v.duration_seconds) : "时长未知"}</span>
                    {v.file_size != null && <span>{fmtSize(v.file_size)}</span>}
                    {v.days_remaining != null && v.days_remaining > 0 ? (
                      <span className="days-tag">剩 {v.days_remaining} 天</span>
                    ) : v.days_remaining === 0 ? (
                      <span className="expired-tag">已过期</span>
                    ) : null}
                  </div>
                </div>
                <div className="video-actions">
                  <button className="btn btn-sm" onClick={() => handlePlay(v)}>播放</button>
                  <button className="btn btn-sm" onClick={() => handleDownload(v)}
                    title="浏览器将保存到你的电脑下载目录">{dlBtnText(v.video_id)}</button>
                  <button className="btn btn-sm btn-error" onClick={() => handleDelete(v)}>删除</button>
                  <div className="feedback-menu">
                    <button className="btn btn-sm" onClick={() => setFeedbackOpen(feedbackOpen === v.video_id ? null : v.video_id)}>反馈 ▾</button>
                    {feedbackOpen === v.video_id && (
                      <div className="feedback-dropdown">
                        <button onClick={() => handleFeedback(v.video_id, "good")}>👍 好用</button>
                        <button onClick={() => handleFeedback(v.video_id, "bad")}>👎 不好用</button>
                        <div style={{ padding: "4px 8px", fontSize: 10, color: "#94a3b8" }}>加入候选池，待审核</div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        {viralTotal > PAGE_SIZE && (
          <div className="pagination">
            <button disabled={viralPage <= 1} onClick={() => setViralPage(p => p - 1)}>上一页</button>
            <span>第 {viralPage} 页 / 共 {Math.ceil(viralTotal / PAGE_SIZE)} 页</span>
            <button disabled={viralPage * PAGE_SIZE >= viralTotal} onClick={() => setViralPage(p => p + 1)}>下一页</button>
          </div>
        )}
      </section>
    </div>
  );
}
