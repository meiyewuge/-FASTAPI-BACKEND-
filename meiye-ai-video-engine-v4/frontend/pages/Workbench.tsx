/**
 * 工作台 — V4 单框工作流（Manus 风格）
 * 三区块：操作对话框 → 母视频/源视频陈列面 → 裂变视频陈列面
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  listVideos, refreshVideoUrl, stableDownload, costSummary,
  strategies as fetchStrategies, uploadFile, batchUpload,
  batchGenerate, pollBatchStatus, deleteVideo, storageStatus,
  trackEvent, videoFeedback,
  getTenant, clearAuth, getToken,
  isAdmin, isSuperAdmin, getUserProfile, fetchMe,
  type VideoItem, type CostSummary, type StrategyItem,
  type BatchUploadItem, type BatchStatus, type StorageStatus,
} from "../api/client";

function fmtDuration(s?: number) {
  if (!s) return "-";
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
  id: string; // 本地唯一ID
  file: File;
  type: "image" | "video" | "file" | "text";
  status: "pending" | "uploading" | "ok" | "failed";
  progress?: number;
  fileUrl?: string;
  fileId?: number;
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
  const [textExtra, setTextExtra] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);

  // ---- 母视频 / 源视频 ----
  const [motherVideos, setMotherVideos] = useState<VideoItem[]>([]);
  const [motherTotal, setMotherTotal] = useState(0);
  const [motherPage, setMotherPage] = useState(1);
  const [motherSelected, setMotherSelected] = useState<Set<number>>(new Set());

  // ---- 裂变视频 ----
  const [viralVideos, setViralVideos] = useState<VideoItem[]>([]);
  const [viralTotal, setViralTotal] = useState(0);
  const [viralPage, setViralPage] = useState(1);
  const [viralSelected, setViralSelected] = useState<Set<number>>(new Set());

  // ---- 批量裂变配置 ----
  const [showBatchConfig, setShowBatchConfig] = useState(false);
  const [batchCount, setBatchCount] = useState(3);
  const [batchStrategy, setBatchStrategy] = useState("mix");
  const [batchPrompt, setBatchPrompt] = useState("");
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null);
  const batchPollRef = useRef(false);

  // ---- 反馈弹出菜单 ----
  const [feedbackOpen, setFeedbackOpen] = useState<number | null>(null);

  // ---- 下载状态 ----
  type DLState = "waiting" | "downloading" | "done" | "error";
  const [dlStates, setDlStates] = useState<Record<number, DLState>>({});

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3500); };
  const PAGE_SIZE = 50;

  // ---- 网络状态 ----
  useEffect(() => {
    const off = () => setOnline(false);
    const on = () => setOnline(true);
    window.addEventListener("offline", off);
    window.addEventListener("online", on);
    return () => { window.removeEventListener("offline", off); window.removeEventListener("online", on); };
  }, []);

  // ---- 获取用户角色 ----
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

  // ---- 加载母视频 ----
  const loadMother = useCallback(async (p = 1) => {
    const r = await listVideos("mother", p, PAGE_SIZE);
    if (r.code === 0) { setMotherVideos(r.data?.items || []); setMotherTotal(r.data?.total || 0); }
  }, []);

  // ---- 加载裂变视频 ----
  const loadViral = useCallback(async (p = 1) => {
    const r = await listVideos("viral", p, PAGE_SIZE);
    if (r.code === 0) { setViralVideos(r.data?.items || []); setViralTotal(r.data?.total || 0); }
  }, []);

  useEffect(() => { loadMother(motherPage); }, [motherPage, loadMother]);
  useEffect(() => { loadViral(viralPage); }, [viralPage, loadViral]);

  // ===================== 上传处理 =====================
  const fileInputRef = useRef<HTMLInputElement>(null);
  const videoInputRef = useRef<HTMLInputElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);

  const handleFilesSelected = (files: FileList | null, type: "image" | "video" | "file") => {
    if (!files) return;
    const maxCounts = { image: 10, video: 10, file: 10 };
    const current = localFiles.filter(f => f.type === type);
    const remaining = maxCounts[type] - current.length;
    if (remaining <= 0) { showToast(`${type === "image" ? "图片" : type === "video" ? "视频" : "文件"}已达上限 ${maxCounts[type]} 个`); return; }

    const arr = Array.from(files).slice(0, remaining);
    const newFiles: LocalFile[] = arr.map((f, i) => ({
      id: `${Date.now()}-${i}`,
      file: f,
      type,
      status: "pending" as const,
    }));
    setLocalFiles(prev => [...prev, ...newFiles]);
  };

  const removeLocalFile = (id: string) => {
    setLocalFiles(prev => prev.filter(f => f.id !== id));
  };

  const uploadAllFiles = async () => {
    const pending = localFiles.filter(f => f.status === "pending");
    if (!pending.length && !prompt.trim() && !textExtra.trim()) {
      showToast("请输入视频需求或上传素材");
      return;
    }
    setUploading(true);
    setUploadProgress(0);

    // 按类型分组上传
    const types: ("image" | "video" | "file")[] = ["image", "video", "file"];
    for (const type of types) {
      const files = pending.filter(f => f.type === type);
      if (!files.length) continue;
      const fileObjs = files.map(f => f.file);
      setLocalFiles(prev => prev.map(f => files.find(x => x.id === f.id) ? { ...f, status: "uploading" as const } : f));

      const r = await batchUpload(fileObjs, type, (pct) => setUploadProgress(pct));
      if (r.code === 0 && r.data) {
        const items = r.data.items || [];
        setLocalFiles(prev => prev.map(f => {
          const idx = files.findIndex(x => x.id === f.id);
          if (idx === -1) return f;
          const item = items[idx];
          if (item?.status === "ok") return { ...f, status: "ok" as const, fileUrl: item.file_url, fileId: item.file_id };
          return { ...f, status: "failed" as const, error: item?.error || "上传失败" };
        }));
      } else {
        setLocalFiles(prev => prev.map(f => files.find(x => x.id === f.id) ? { ...f, status: "failed" as const, error: r.message } : f));
      }
    }
    setUploading(false);
    setUploadProgress(100);
    // 刷新母视频列表（上传的视频会出现在列表中）
    loadMother(1);
    loadDashboard();
    showToast("素材上传完成");
  };

  // ===================== 操作按钮 =====================
  const handleAGenerate = async () => {
    if (!prompt.trim()) { showToast("请输入视频需求"); return; }
    if (!confirm("A 台母视频生成会产生费用，确认继续？")) return;
    // P0 阶段不自动触发 A 台，仅提示
    showToast("A 台功能请谨慎使用，请联系管理员操作");
  };

  const handleOpenBatchConfig = () => {
    if (motherSelected.size === 0) {
      showToast("请先在下方母视频陈列面勾选 1~10 个源视频");
      return;
    }
    if (motherSelected.size > 10) {
      showToast("最多选择 10 个源视频");
      return;
    }
    setShowBatchConfig(true);
  };

  const handleBatchSubmit = async () => {
    const sourceIds = Array.from(motherSelected);
    const totalOutputs = sourceIds.length * batchCount;
    if (totalOutputs > 50) {
      showToast(`总产出 ${totalOutputs} 条超过上限 50，请减少数量`);
      return;
    }
    if (!confirm(`确认裂变 ${sourceIds.length} 个源视频 × ${batchCount} 条 = ${totalOutputs} 条？`)) return;
    setBatchRunning(true);
    setBatchStatus(null);
    trackEvent("send_to_b", { source_ids: sourceIds, count: batchCount });

    const r = await batchGenerate(sourceIds, batchCount, batchStrategy, batchPrompt || undefined);
    if (r.code === 0 && r.data) {
      const batchId = r.data.batch_id;
      showToast(`裂变任务已提交 (${batchId})，开始轮询...`);
      batchPollRef.current = true;
      pollBatchStatus(batchId, (d) => {
        setBatchStatus(d);
      }).then((final) => {
        batchPollRef.current = false;
        setBatchRunning(false);
        if (final.data?.status === "done") {
          showToast(`裂变完成！产出 ${final.data.completed}/${final.data.total_outputs} 条`);
          loadViral(1);
          loadDashboard();
        } else {
          showToast(`裂变任务结束: ${final.data?.status || "未知状态"}`);
        }
      });
    } else {
      showToast(r.message || "提交裂变失败");
      setBatchRunning(false);
    }
  };

  // ===================== 视频操作 =====================
  const handlePlay = (v: VideoItem) => {
    trackEvent("video_play", { video_id: v.video_id });
    if (v.download_url) window.open(v.download_url, "_blank");
    else if (v.share_url) window.open(v.share_url, "_blank");
  };

  const handleDownload = async (v: VideoItem) => {
    if (!v.download_url) { showToast("暂无下载链接"); return; }
    trackEvent("video_download", { video_id: v.video_id });
    setDlStates(p => ({ ...p, [v.video_id]: "downloading" }));
    const r = await stableDownload(v);
    setDlStates(p => ({ ...p, [v.video_id]: r.ok ? "done" : "error" }));
    if (!r.ok) showToast(r.error || "下载失败");
    setTimeout(() => setDlStates(p => { const n = { ...p }; delete n[v.video_id]; return n; }), 3000);
  };

  const handleBatchDownload = async (list: VideoItem[]) => {
    const ok = list.filter(v => v.download_url);
    if (!ok.length) { showToast("没有可下载的视频"); return; }
    showToast(`开始下载 ${ok.length} 个视频...`);
    let count = 0;
    for (let i = 0; i < ok.length; i++) {
      setDlStates(p => ({ ...p, [ok[i].video_id]: "downloading" }));
      const r = await stableDownload(ok[i]);
      setDlStates(p => ({ ...p, [ok[i].video_id]: r.ok ? "done" : "error" }));
      if (r.ok) count++;
      if (i < ok.length - 1) await new Promise(r => setTimeout(r, 300));
    }
    showToast(`下载完成：${count}/${ok.length} 成功`);
  };

  const handleDelete = async (v: VideoItem) => {
    if (!confirm(`确认删除视频 #${v.video_id}？此操作不可恢复。`)) return;
    const r = await deleteVideo(v.video_id);
    if (r.code === 0) {
      trackEvent("video_delete", { video_id: v.video_id });
      showToast(`视频 #${v.video_id} 已删除`);
      if (v.type === "viral") loadViral(viralPage);
      else loadMother(motherPage);
      loadDashboard();
    } else {
      showToast(r.message || (r.code === 403 || r.code === 2001 ? "无权删除该视频" : "删除失败"));
    }
  };

  const handleFeedback = async (videoId: number, action: "favorite" | "useful" | "useless" | "note") => {
    setFeedbackOpen(null);
    const r = await videoFeedback(videoId, action);
    if (r.code === 0) showToast(`反馈已提交: ${action === "favorite" ? "收藏" : action === "useful" ? "好用" : action === "useless" ? "不好用" : "备注"}`);
    else showToast(r.message || "反馈提交失败");
  };

  // ===================== 选择操作 =====================
  const toggleMother = (id: number) => {
    setMotherSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      trackEvent("video_select", { video_id: id });
      return next;
    });
  };
  const toggleAllMother = () => {
    if (motherSelected.size === motherVideos.length) setMotherSelected(new Set());
    else setMotherSelected(new Set(motherVideos.map(v => v.video_id)));
  };
  const toggleViral = (id: number) => {
    setViralSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };
  const toggleAllViral = () => {
    if (viralSelected.size === viralVideos.length) setViralSelected(new Set());
    else setViralSelected(new Set(viralVideos.map(v => v.video_id)));
  };

  // ===================== 汇总统计 =====================
  const imageFiles = localFiles.filter(f => f.type === "image");
  const videoFiles = localFiles.filter(f => f.type === "video");
  const docFiles = localFiles.filter(f => f.type === "file");
  const hasText = !!(prompt.trim() || textExtra.trim());
  const hasUploads = localFiles.length > 0;
  const sourceCount = motherSelected.size;
  const batchTotal = sourceCount * batchCount;

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
          placeholder="请输入视频需求，或上传素材开始创作…"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
        />

        {/* 上传区 */}
        <div className="upload-zone">
          <label className="upload-btn">
            🖼️ 图片
            <input ref={imageInputRef} type="file" accept=".jpg,.jpeg,.png,.webp" multiple
              onChange={(e) => { handleFilesSelected(e.target.files, "image"); e.target.value = ""; }} />
          </label>
          <label className="upload-btn">
            📁 文件
            <input type="file" accept=".doc,.docx,.zip" multiple
              onChange={(e) => { handleFilesSelected(e.target.files, "file"); e.target.value = ""; }} />
          </label>
          <label className="upload-btn">
            🎬 视频
            <input ref={videoInputRef} type="file" accept=".mp4,.mov,.avi" multiple
              onChange={(e) => { handleFilesSelected(e.target.files, "video"); e.target.value = ""; }} />
          </label>
          <button className="upload-btn" onClick={() => {
            const txt = window.prompt("输入脚本/分镜/口播要求:");
            if (txt) setTextExtra(prev => prev ? prev + "\n" + txt : txt);
          }}>📝 文本</button>
        </div>

        {/* 素材汇总条 */}
        {(hasUploads || hasText) && (
          <div className="upload-summary">
            {imageFiles.length > 0 && <span className="upload-summary-item">🖼️ 图片 x{imageFiles.length}</span>}
            {docFiles.length > 0 && <><span className="upload-summary-sep">/</span><span className="upload-summary-item">📁 文件 x{docFiles.length}</span></>}
            {videoFiles.length > 0 && <><span className="upload-summary-sep">/</span><span className="upload-summary-item">🎬 视频 x{videoFiles.length}</span></>}
            {hasText && <><span className="upload-summary-sep">/</span><span className="upload-summary-item">📝 文本已输入</span></>}
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

        {/* 操作按钮 */}
        <div className="action-bar">
          <button className="btn btn-a" onClick={handleAGenerate} disabled={uploading || !online}
            title="A台母视频生成，会产生费用，请谨慎使用">
            🎬 A台·母视频（⚠️会产生费用）
          </button>
          <button className="btn btn-b" onClick={handleOpenBatchConfig}
            disabled={uploading || !online || motherVideos.length === 0 && motherSelected.size === 0}
            title="B台本地ffmpeg裂变，0 AI成本。请先上传3~5个视频，或选择已有母视频">
            🔁 B台·裂变（0 元/条）
          </button>
          {hasUploads && (
            <button className="btn btn-primary" onClick={uploadAllFiles} disabled={uploading || !online}>
              {uploading ? `上传中 ${uploadProgress}%` : "📤 上传素材"}
            </button>
          )}
        </div>

        {/* 文本额外输入 */}
        {textExtra && (
          <div style={{ marginTop: 12, padding: "8px 12px", background: "#f0f9ff", borderRadius: 8, fontSize: 13, color: "#0369a1" }}>
            📝 附加文本: {textExtra.slice(0, 80)}{textExtra.length > 80 ? "…" : ""}
            <button onClick={() => setTextExtra("")} style={{ marginLeft: 8, color: "#ef4444", background: "none", border: "none", cursor: "pointer", fontSize: 12 }}>清除</button>
          </div>
        )}
      </section>

      {/* ===== 批量裂变配置面板 ===== */}
      {showBatchConfig && (
        <div className="batch-config-panel">
          <h4>🔁 B台裂变配置</h4>
          <div className="batch-config-row">
            <label>已选源视频</label>
            <span style={{ fontWeight: 600 }}>{sourceCount} 个</span>
            <button className="btn btn-sm" onClick={() => { setMotherSelected(new Set()); setShowBatchConfig(false); }}>重选</button>
          </div>
          <div className="batch-config-row">
            <label>每个源裂变数</label>
            <input type="number" min={1} max={10} value={batchCount}
              onChange={(e) => setBatchCount(Math.max(1, Math.min(10, parseInt(e.target.value) || 1)))} />
          </div>
          <div className="batch-config-row">
            <label>裂变策略</label>
            <select value={batchStrategy} onChange={(e) => setBatchStrategy(e.target.value)}>
              {strats.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </div>
          <div className="batch-config-row">
            <label>补充 Prompt</label>
            <input type="text" placeholder="可选：叠加文案要求" value={batchPrompt}
              onChange={(e) => setBatchPrompt(e.target.value)} style={{ width: 240 }} />
          </div>
          <div className="batch-estimate">
            预计产出: <strong>{sourceCount}</strong> 个源 × <strong>{batchCount}</strong> 条 = <strong>{batchTotal}</strong> 条
            {batchTotal > 50 && <span style={{ color: "#dc2626", marginLeft: 8 }}>⚠️ 超过上限 50</span>}
          </div>

          {/* 批量进度 */}
          {batchStatus && (
            <div className="batch-progress">
              <div className="batch-progress-header">
                <span>{batchStatus.status === "running" ? "裂变中..." : batchStatus.status === "done" ? "裂变完成" : "裂变失败"}</span>
                <span>{batchStatus.completed} / {batchStatus.total_outputs}</span>
              </div>
              <div className="progress-bar">
                <div className="progress-fill" style={{
                  width: `${batchStatus.total_outputs > 0 ? (batchStatus.completed / batchStatus.total_outputs * 100) : 0}%`
                }} />
              </div>
            </div>
          )}

          <div className="batch-submit-row">
            <button className="btn btn-b" onClick={handleBatchSubmit}
              disabled={batchRunning || batchTotal > 50 || !online}>
              {batchRunning ? "裂变中..." : `开始裂变 (${batchTotal} 条)`}
            </button>
            <button className="btn" onClick={() => setShowBatchConfig(false)}>取消</button>
          </div>
        </div>
      )}

      {/* ===== 区块二：母视频 / 源视频陈列面 ===== */}
      <section className="video-gallery">
        <div className="gallery-header">
          <h3>母视频 / 源视频<span className="gallery-count">({motherTotal})</span></h3>
          <div className="gallery-toolbar">
            <button className="btn" onClick={toggleAllMother}>
              {motherSelected.size === motherVideos.length ? "取消全选" : "全选"}
            </button>
            {motherSelected.size > 0 && (
              <>
                <span style={{ fontSize: 12, color: "#64748b" }}>已选 {motherSelected.size}</span>
                <button className="btn" onClick={() => handleBatchDownload(motherVideos.filter(v => motherSelected.has(v.video_id)))}>下载选中</button>
                <button className="btn btn-b" onClick={handleOpenBatchConfig}>🔁 发送到B台裂变</button>
              </>
            )}
          </div>
        </div>

        {motherVideos.length === 0 ? (
          <div className="empty-state">暂无母视频/源视频。请上传素材或使用A台生成。</div>
        ) : (
          <div className="video-grid">
            {motherVideos.map(v => (
              <div key={v.video_id} className={`video-card ${motherSelected.has(v.video_id) ? "selected" : ""}`}
                onClick={() => toggleMother(v.video_id)}>
                <label className="video-checkbox" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={motherSelected.has(v.video_id)}
                    onChange={() => toggleMother(v.video_id)} />
                </label>
                <div className="video-preview" onClick={(e) => { e.stopPropagation(); handlePlay(v); }}>
                  {v.cover_url ? <img className="video-cover" src={v.cover_url} alt="" /> :
                    v.download_url ? <video src={v.download_url} muted /> :
                      <span className="video-placeholder">暂无预览</span>}
                  <span className={`video-source-badge ${v.source === "upload" ? "source-upload" : "source-a"}`}>
                    {v.source === "upload" ? "上传" : "A台生成"}
                  </span>
                </div>
                <div className="video-info">
                  <div className="video-title">{v.title || `视频 #${v.video_id}`}</div>
                  <div className="video-meta">
                    <span className="video-id">#{v.video_id}</span>
                    {v.duration != null && <span>{fmtDuration(v.duration)}</span>}
                    {v.file_size != null && <span>{fmtSize(v.file_size)}</span>}
                    {v.created_at && <span>{new Date(v.created_at).toLocaleDateString("zh-CN")}</span>}
                  </div>
                </div>
                <div className="video-actions" onClick={(e) => e.stopPropagation()}>
                  <button className="btn btn-sm" onClick={() => handlePlay(v)}>播放</button>
                  <button className="btn btn-sm" onClick={() => handleDownload(v)}>{dlBtnText(v.video_id)}</button>
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
      <section className="video-gallery">
        <div className="gallery-header">
          <h3>裂变视频<span className="gallery-count">({viralTotal})</span></h3>
          <div className="gallery-toolbar">
            <button className="btn" onClick={toggleAllViral}>
              {viralSelected.size === viralVideos.length ? "取消全选" : "全选"}
            </button>
            {viralSelected.size > 0 && (
              <>
                <span style={{ fontSize: 12, color: "#64748b" }}>已选 {viralSelected.size}</span>
                <button className="btn" onClick={() => handleBatchDownload(viralVideos.filter(v => viralSelected.has(v.video_id)))}>下载选中</button>
                <button className="btn btn-error" onClick={async () => {
                  const ids = Array.from(viralSelected);
                  if (!confirm(`确认删除 ${ids.length} 个视频？`)) return;
                  for (const id of ids) await deleteVideo(id);
                  showToast(`已删除 ${ids.length} 个视频`);
                  loadViral(viralPage);
                  loadDashboard();
                }}>删除选中</button>
              </>
            )}
          </div>
        </div>

        <div className="viral-notice">
          ⏰ 裂变视频服务器临时保留 5 天，请及时下载到本地。
        </div>

        {viralVideos.length === 0 ? (
          <div className="empty-state">暂无裂变视频。请在上方选择母视频并点击"发送到B台裂变"。</div>
        ) : (
          <div className="video-grid">
            {viralVideos.map(v => (
              <div key={v.video_id} className={`video-card ${viralSelected.has(v.video_id) ? "selected" : ""}`}
                onClick={() => toggleViral(v.video_id)}>
                <label className="video-checkbox" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={viralSelected.has(v.video_id)}
                    onChange={() => toggleViral(v.video_id)} />
                </label>
                <div className="video-preview" onClick={(e) => { e.stopPropagation(); handlePlay(v); }}>
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
                    {v.duration != null && <span>{fmtDuration(v.duration)}</span>}
                    {v.file_size != null && <span>{fmtSize(v.file_size)}</span>}
                    {v.days_remaining != null && v.days_remaining > 0 ? (
                      <span className="days-tag">剩 {v.days_remaining} 天</span>
                    ) : v.days_remaining === 0 ? (
                      <span className="expired-tag">已过期</span>
                    ) : null}
                  </div>
                </div>
                <div className="video-actions" onClick={(e) => e.stopPropagation()}>
                  <button className="btn btn-sm" onClick={() => handlePlay(v)}>播放</button>
                  <button className="btn btn-sm" onClick={() => handleDownload(v)}
                    title="浏览器将保存到你的电脑下载目录">{dlBtnText(v.video_id)}</button>
                  <button className="btn btn-sm btn-error" onClick={() => handleDelete(v)}>删除</button>
                  <div className="feedback-menu">
                    <button className="btn btn-sm" onClick={() => setFeedbackOpen(feedbackOpen === v.video_id ? null : v.video_id)}>更多 ▾</button>
                    {feedbackOpen === v.video_id && (
                      <div className="feedback-dropdown">
                        <button onClick={() => handleFeedback(v.video_id, "favorite")}>⭐ 收藏</button>
                        <button onClick={() => handleFeedback(v.video_id, "useful")}>👍 好用</button>
                        <button onClick={() => handleFeedback(v.video_id, "useless")}>👎 不好用</button>
                        <button onClick={() => {
                          const note = window.prompt("输入备注:");
                          if (note) handleFeedback(v.video_id, "note");
                        }}>📝 备注</button>
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
