/**
 * 工作台 — V4 P0-B + P1 单框工作流
 *
 * 依据：FRONTEND_V4_CURRENT_API_CONTRACT.md（唯一接口真源）
 *
 * A台流程：prompt + 图片 + 风格 → POST /compose/preview → 展示导演稿 → 确认 → POST /compose
 * B台流程：current_source_video_ids → duration_seconds >= 30 门槛 → POST /b/batch-generate → 轮询
 *
 * 核心特性：
 *  - compose preview（不花钱、不调火山）→ 导演分镜 + image_roles + seedance_text_prompt + estimated_cost
 *  - 图片 role 自动分配（第1张=首帧，2-9张=参考图）+ 拖拽排序
 *  - localStorage 草稿恢复（debounce 500ms）
 *  - 4031 熔断锁 → 按钮置灰 + 文案
 *  - 2002 图片不可访问 → 明确提示
 *  - current_source_video_ids 会话源池
 *  - B台 duration_seconds >= 30 硬门槛（≥3 合格源才可用）
 *  - Patch6 权限不破坏
 */
import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  listVideos, refreshVideoUrl, stableDownload, costSummary,
  strategies as fetchStrategies, batchUpload,
  batchGenerate, pollBatchStatus, deleteVideo, storageStatus,
  trackEvent, videoFeedback, composePreview, compose, pollTask,
  getTenant, clearAuth, getToken,
  isAdmin, isSuperAdmin, getUserProfile, fetchMe,
  type VideoItem, type CostSummary, type StrategyItem,
  type BatchStatus, type StorageStatus, type TaskData,
  type ComposePreviewResult, type StoryboardItem, type ImageRoleItem,
} from "../api/client";

const LS_DRAFT_KEY = "v4_compose_draft";

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

// ====================== 本地类型 ======================
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

interface UploadedImage {
  fileId: number;
  fileName: string;
  previewUrl: string; // local blob URL for display
}

// ====================== 草稿序列化 ======================
interface ComposeDraft {
  prompt: string;
  imageFileIds: number[];
  style: string;
  ratio: string;
  duration: number;
  resolution: string;
}

function saveDraft(d: ComposeDraft) {
  try { localStorage.setItem(LS_DRAFT_KEY, JSON.stringify(d)); } catch { /* ignore */ }
}
function loadDraft(): ComposeDraft | null {
  try {
    const raw = localStorage.getItem(LS_DRAFT_KEY);
    return raw ? JSON.parse(raw) as ComposeDraft : null;
  } catch { return null; }
}
function clearDraft() {
  try { localStorage.removeItem(LS_DRAFT_KEY); } catch { /* ignore */ }
}

// ====================== 组件 ======================
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

  // ---- 图片管理（role 排序）----
  const [uploadedImages, setUploadedImages] = useState<UploadedImage[]>([]);
  const [dragImageIdx, setDragImageIdx] = useState<number | null>(null);

  // ---- A台配置 ----
  const [aStyle, setAStyle] = useState("premium");
  const [aRatio, setARatio] = useState("9:16");
  const [aDuration, setADuration] = useState(15);
  const [aResolution, setAResolution] = useState("1080p");

  // ---- A台 Preview ----
  const [previewResult, setPreviewResult] = useState<ComposePreviewResult | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [promptExpanded, setPromptExpanded] = useState(false);

  // ---- A台 Compose ----
  const [composeRunning, setComposeRunning] = useState(false);
  const [composeProgress, setComposeProgress] = useState("");
  const [composeMaintenance, setComposeMaintenance] = useState(false); // 4031 维护态

  // ---- 母视频 / 源视频 ----
  const [motherVideos, setMotherVideos] = useState<VideoItem[]>([]);
  const [motherTotal, setMotherTotal] = useState(0);
  const [motherPage, setMotherPage] = useState(1);

  // ---- 裂变视频 ----
  const [viralVideos, setViralVideos] = useState<VideoItem[]>([]);
  const [viralTotal, setViralTotal] = useState(0);
  const [viralPage, setViralPage] = useState(1);

  // ---- B台会话源视频池 ----
  const [currentSourceVideoIds, setCurrentSourceVideoIds] = useState<number[]>([]);
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchStatus, setBatchStatus] = useState<BatchStatus | null>(null);
  const [batchIgnored, setBatchIgnored] = useState<number[]>([]);

  // ---- 反馈 / 下载 ----
  const [feedbackOpen, setFeedbackOpen] = useState<number | null>(null);
  type DLState = "waiting" | "downloading" | "done" | "error";
  const [dlStates, setDlStates] = useState<Record<number, DLState>>({});

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3500); };
  const PAGE_SIZE = 50;
  const viralRef = useRef<HTMLElement>(null);
  const draftTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---- 合格源计算（duration_seconds >= 30） ----
  const qualifiedSources = useMemo(() =>
    currentSourceVideoIds.filter(id => {
      const v = motherVideos.find(m => m.video_id === id);
      return v && v.duration_seconds != null && v.duration_seconds >= 30;
    }),
    [currentSourceVideoIds, motherVideos],
  );
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

  // ---- 草稿恢复 ----
  useEffect(() => {
    const d = loadDraft();
    if (d) {
      setPrompt(d.prompt || "");
      setAStyle(d.style || "premium");
      setARatio(d.ratio || "9:16");
      setADuration(d.duration || 15);
      setAResolution(d.resolution || "1080p");
      // imageFileIds 恢复：如果上传的图片还在 localStorage 里则恢复
      // （注意：blob URL 失效，只显示 fileId）
      if (d.imageFileIds?.length) {
        setUploadedImages(d.imageFileIds.map(fid => ({
          fileId: fid, fileName: `图片 #${fid}`, previewUrl: "",
        })));
      }
    }
  }, []);

  // ---- 草稿自动保存（debounce 500ms）----
  useEffect(() => {
    if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    draftTimerRef.current = setTimeout(() => {
      saveDraft({
        prompt,
        imageFileIds: uploadedImages.map(i => i.fileId),
        style: aStyle, ratio: aRatio, duration: aDuration, resolution: aResolution,
      });
    }, 500);
    return () => { if (draftTimerRef.current) clearTimeout(draftTimerRef.current); };
  }, [prompt, uploadedImages, aStyle, aRatio, aDuration, aResolution]);

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

  // ===================== 上传（自动上传，图片追踪 fileId）=====================
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

      // 视频 → video_id 加入源池
      if (type === "video") {
        const newIds = uploaded.filter(u => u.video_id != null).map(u => u.video_id!);
        if (newIds.length > 0) setCurrentSourceVideoIds(prev => [...prev, ...newIds]);
      }

      // 图片 → 追踪 fileId + previewUrl（用于 A台 preview 的 image_file_ids）
      if (type === "image") {
        const newImages: UploadedImage[] = [];
        files.forEach((f, idx) => {
          const item = uploaded[idx];
          if (item && item.status !== "failed" && item.file_id) {
            newImages.push({
              fileId: item.file_id,
              fileName: f.file.name,
              previewUrl: URL.createObjectURL(f.file),
            });
          }
        });
        if (newImages.length > 0) setUploadedImages(prev => [...prev, ...newImages]);
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

  // ===================== 图片拖拽排序（role 自动更新）=====================
  const handleImageDragStart = (idx: number) => setDragImageIdx(idx);
  const handleImageDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    if (dragImageIdx === null || dragImageIdx === idx) return;
    setUploadedImages(prev => {
      const next = [...prev];
      const [moved] = next.splice(dragImageIdx, 1);
      next.splice(idx, 0, moved);
      return next;
    });
    setDragImageIdx(idx);
  };
  const handleImageDragEnd = () => setDragImageIdx(null);
  const removeImage = (idx: number) => {
    setUploadedImages(prev => prev.filter((_, i) => i !== idx));
  };

  // ===================== A台 Preview =====================
  const handlePreview = async () => {
    if (!prompt.trim()) { showToast("请先描述需求"); return; }
    setPreviewLoading(true);
    setPreviewResult(null);
    trackEvent("preview", { prompt: prompt.slice(0, 50) });

    const imageFileIds = uploadedImages.map(img => img.fileId);
    const r = await composePreview(prompt, imageFileIds.length ? imageFileIds : undefined, aStyle, aRatio, aDuration, aResolution);

    setPreviewLoading(false);
    if (r.code === 0 && r.data) {
      setPreviewResult(r.data);
    } else if (r.code === 2002) {
      showToast("图片无法被视频模型访问，请重新上传或等待处理完成。");
    } else {
      showToast(r.message || "预览失败");
    }
  };

  // ===================== A台 Compose（确认后生成）=====================
  const handleComposeConfirm = async () => {
    if (!previewResult?.director_plan_id) { showToast("请先预览导演稿"); return; }
    const est = previewResult.estimated_cost;
    const ok = window.confirm(`本次生成预计消耗 ¥${est.toFixed(2)}（以实际扣费为准）。确认继续吗？`);
    if (!ok) return;

    setComposeRunning(true);
    setComposeProgress("正在提交生成任务…");
    trackEvent("send_to_a", { prompt: prompt.slice(0, 50), plan_id: previewResult.director_plan_id });

    const r = await compose(previewResult.director_plan_id, true, previewResult.duration);

    if (r.code === 0 && r.data?.task_id) {
      clearDraft(); // 提交成功清除草稿
      setComposeProgress("正在生成母视频…");
      pollTask(r.data.task_id, (d: TaskData) => {
        if (d.status === "running") setComposeProgress(`生成中… ${Math.round((d.progress || 0) * 100)}%`);
        if (d.status === "done") setComposeProgress("拼接中…");
      }).then((final) => {
        setComposeRunning(false);
        setComposeProgress("");
        if (final.data?.status === "done") {
          const vids = final.data.result?.videos || [];
          const newIds = vids.filter(v => v.video_id).map(v => v.video_id);
          if (newIds.length > 0) setCurrentSourceVideoIds(prev => [...prev, ...newIds]);
          showToast("母视频已生成");
          setPreviewResult(null);
          loadMother(1);
          loadDashboard();
        } else {
          const err = final.data?.error || final.message || "生成失败";
          if (final.code === 4029) showToast("额度不足，请联系管理员充值或开通。");
          else showToast(err);
        }
      });
    } else if (r.code === 4031) {
      setComposeRunning(false);
      setComposeProgress("");
      setComposeMaintenance(true);
      showToast("生成通道维护中，暂不可用。");
    } else if (r.code === 4029) {
      setComposeRunning(false);
      setComposeProgress("");
      showToast("额度不足，请联系管理员充值或开通。");
    } else if (r.code === 3001) {
      setComposeRunning(false);
      setComposeProgress("");
      showToast("导演稿已过期，请重新预览。");
      setPreviewResult(null);
    } else if (r.code === 2002) {
      setComposeRunning(false);
      setComposeProgress("");
      showToast("图片无法被视频模型访问，请重新上传或等待处理完成。");
    } else {
      setComposeRunning(false);
      setComposeProgress("");
      showToast(r.message || "提交生成失败");
    }
  };

  // ===================== B台裂变 =====================
  const handleBClick = async () => {
    if (qualifiedCount < 3) {
      const maxD = motherVideos.reduce((m, v) => {
        const d = v.duration_seconds; return d != null && d > m ? d : m;
      }, 0);
      showToast(`请至少上传3个时长30秒以上的视频。当前：${currentSourceVideoIds.length}个视频，最长${Math.round(maxD)}秒`);
      return;
    }
    const sourceIds = qualifiedSources.slice(0, 5);
    setBatchRunning(true);
    setBatchStatus(null);
    setBatchIgnored([]);
    trackEvent("send_to_b", { source_ids: sourceIds });

    const r = await batchGenerate(sourceIds, prompt || undefined);
    if (r.code === 0 && r.data) {
      const { batch_id, ignored_source_video_ids } = r.data;
      if (ignored_source_video_ids?.length) {
        setBatchIgnored(ignored_source_video_ids);
        showToast(`部分视频未参与本轮裂变，本轮最多使用5个合格源视频`);
      }
      showToast(`裂变任务已提交…`);
      pollBatchStatus(batch_id, (d) => setBatchStatus(d)).then((final) => {
        setBatchRunning(false);
        if (final.data?.status === "done") {
          const c = final.data.completed || 0, f = final.data.failed || 0;
          showToast(f > 0 ? `部分失败，成功 ${c} 条` : `裂变完成！${c} 条`);
          loadViral(1, batch_id);
          loadDashboard();
          setTimeout(() => viralRef.current?.scrollIntoView({ behavior: "smooth" }), 300);
        } else if (final.data?.status === "partial_done") {
          const c = final.data.completed || 0, f = final.data.failed || 0;
          showToast(`部分视频生成成功（${c} 条），失败项已跳过（${f} 条），可先查看已生成视频。`);
          loadViral(1, batch_id);
          loadDashboard();
          setTimeout(() => viralRef.current?.scrollIntoView({ behavior: "smooth" }), 300);
        } else {
          showToast(`裂变结束: ${final.data?.status || "未知"}`);
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
    window.open(v.download_url || v.share_url, "_blank");
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
      if (v.type === "viral") loadViral(viralPage); else loadMother(motherPage);
      loadDashboard();
      setCurrentSourceVideoIds(prev => prev.filter(id => id !== v.video_id));
    } else {
      showToast(r.code === 403 ? "无权删除其他租户的视频" : (r.message || "删除失败"));
    }
  };
  const handleFeedback = async (videoId: number, rating: "good" | "bad") => {
    setFeedbackOpen(null);
    const note = rating === "bad" ? (window.prompt("输入备注（可选）:") || undefined) : undefined;
    const r = await videoFeedback(videoId, rating, undefined, note);
    if (r.code === 0) showToast("已加入候选池，待审核");
    else showToast(r.message || "反馈提交失败，请重试");
  };

  // ===================== 汇总 =====================
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
          <button className="btn btn-admin" onClick={() => navigate("/p2a-preview")} title="P2A 预览工作台" style={{background:"#6366f1",color:"#fff"}}>📋 P2A 预览</button>
          <button className="btn btn-admin" onClick={() => navigate("/p2b-preview")} title="P2B-A 后期制作脑子预览" style={{background:"#8b5cf6",color:"#fff"}}>🎬 P2B-A 预览</button>
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
          placeholder="描述你的需求，例如：达芙荻丽奢华油，夏季干皮上妆卡粉救星，99%天然植萃…"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
        />

        {/* 上传区 */}
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
            <span className="upload-summary-link" onClick={() => { setLocalFiles([]); setUploadedImages([]); }}>清除全部</span>
          </div>
        )}

        {/* 上传缩略图（非图片） */}
        {localFiles.filter(f => f.type !== "image").length > 0 && (
          <div className="upload-thumbs">
            {localFiles.filter(f => f.type !== "image").map(f => (
              <div key={f.id} className="upload-thumb">
                {f.type === "video" ? (
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

        {/* 图片角色排序区（拖拽调整顺序，role 自动更新） */}
        {uploadedImages.length > 0 && (
          <div className="image-role-section">
            <div className="image-role-header">
              <span>📸 已上传图片（拖拽调整顺序，第 1 张 = 首帧，其余 = 参考图）</span>
              <span className="image-role-hint">角色自动分配</span>
            </div>
            <div className="image-role-list">
              {uploadedImages.map((img, idx) => (
                <div
                  key={img.fileId}
                  className={`image-role-card ${dragImageIdx === idx ? "dragging" : ""}`}
                  draggable
                  onDragStart={() => handleImageDragStart(idx)}
                  onDragOver={(e) => handleImageDragOver(e, idx)}
                  onDragEnd={handleImageDragEnd}
                >
                  <div className="image-role-thumb">
                    {img.previewUrl ? <img src={img.previewUrl} alt={img.fileName} /> :
                      <div className="image-role-placeholder">#{img.fileId}</div>}
                  </div>
                  <div className="image-role-info">
                    <span className="image-role-name">{img.fileName}</span>
                    <span className={`image-role-badge ${idx === 0 ? "role-first" : "role-ref"}`}>
                      {idx === 0 ? "首帧" : "参考图"}
                    </span>
                  </div>
                  <button className="image-role-remove" onClick={() => removeImage(idx)}>✕</button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 上传进度 */}
        {uploading && (
          <div className="upload-progress-bar">
            <div className="upload-progress-fill" style={{ width: `${uploadProgress}%` }} />
          </div>
        )}

        {/* A台配置行 */}
        <div className="compose-config">
          <label>风格
            <select value={aStyle} onChange={(e) => setAStyle(e.target.value)}>
              <option value="premium">高端奢华</option>
              <option value="fresh">清新自然</option>
              <option value="chinese">东方美学</option>
            </select>
          </label>
          <label>比例
            <select value={aRatio} onChange={(e) => setARatio(e.target.value)}>
              <option value="9:16">9:16 竖屏</option>
              <option value="16:9">16:9 横屏</option>
              <option value="1:1">1:1 方形</option>
            </select>
          </label>
          <label>时长
            <select value={aDuration} onChange={(e) => setADuration(Number(e.target.value))}>
              <option value={15}>15 秒</option>
              <option value={30}>30 秒</option>
              <option value={60}>60 秒</option>
            </select>
          </label>
          <label>分辨率
            <select value={aResolution} onChange={(e) => setAResolution(e.target.value)}>
              <option value="1080p">1080p</option>
              <option value="720p">720p</option>
            </select>
          </label>
        </div>

        {/* 操作按钮 */}
        <div className="action-bar">
          <button className="btn btn-preview" onClick={handlePreview}
            disabled={previewLoading || composeRunning || !online || !prompt.trim()}
            title="预览导演稿（不花钱）">
            {previewLoading ? "预览中…" : "🎬 预览导演稿"}
          </button>
          <button className={`btn btn-a ${composeMaintenance ? "btn-maintenance" : ""}`}
            onClick={handleComposeConfirm}
            disabled={!previewResult || composeRunning || batchRunning || !online || composeMaintenance}
            title={composeMaintenance ? "生成通道维护中" : previewResult ? `确认生成（预计 ¥${previewResult.estimated_cost.toFixed(2)}）` : "请先预览导演稿"}>
            {composeMaintenance ? "🔧 生成通道维护中" : "🎬 A台·生成母视频（⚠️ 会产生费用）"}
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

        {/* ===== Preview 展示面板 ===== */}
        {previewResult && (
          <div className="preview-panel">
            <div className="preview-header">
              <h3>🎬 导演稿预览</h3>
              <span className="preview-plan-id">plan: {previewResult.director_plan_id}</span>
            </div>

            {/* Warnings */}
            {previewResult.warnings?.length > 0 && (
              <div className="preview-warnings">
                {previewResult.warnings.map((w, i) => (
                  <div key={i} className="preview-warning">⚠️ {w}</div>
                ))}
              </div>
            )}

            {/* 品牌上下文 */}
            {previewResult.director_plan?.brand_context && (
              <div className="preview-brand">
                {previewResult.director_plan.brand_context.brand && (
                  <span>品牌: <strong>{previewResult.director_plan.brand_context.brand}</strong></span>
                )}
                {previewResult.director_plan.brand_context.product && (
                  <span>产品: {previewResult.director_plan.brand_context.product}</span>
                )}
                {previewResult.director_plan.brand_context.selling_points?.length ? (
                  <span>卖点: {previewResult.director_plan.brand_context.selling_points.join("、")}</span>
                ) : null}
              </div>
            )}

            {/* 分镜卡片 */}
            {previewResult.director_plan?.storyboard?.length > 0 && (
              <div className="storyboard-section">
                <h4>分镜</h4>
                <div className="storyboard-list">
                  {previewResult.director_plan.storyboard.map((shot: StoryboardItem) => (
                    <div key={shot.index} className="storyboard-card">
                      <div className="sb-header">
                        <span className="sb-index">#{shot.index}</span>
                        <span className="sb-timecode">{shot.timecode}</span>
                      </div>
                      <div className="sb-desc">{shot.description}</div>
                      {shot.line && <div className="sb-line">🎙️ {shot.line}</div>}
                      {shot.image_ref && <div className="sb-imgref">📷 {shot.image_ref}</div>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 图片角色 */}
            {previewResult.image_roles?.length > 0 && (
              <div className="preview-image-roles">
                <h4>图片角色</h4>
                <div className="role-chips">
                  {previewResult.image_roles.map((ir: ImageRoleItem, i: number) => (
                    <span key={i} className={`role-chip ${ir.role === "first_frame" ? "role-first" : "role-ref"}`}>
                      {ir.role === "first_frame" ? "首帧" : "参考图"} #{ir.file_id}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Seedance 提示词 */}
            {previewResult.seedance_text_prompt && (
              <div className="preview-seedance">
                <h4 onClick={() => setPromptExpanded(!promptExpanded)} style={{ cursor: "pointer" }}>
                  {promptExpanded ? "▼" : "▶"} Seedance 提示词（T1-T5）
                </h4>
                {promptExpanded && (
                  <pre className="seedance-prompt">{previewResult.seedance_text_prompt}</pre>
                )}
              </div>
            )}

            {/* 费用预估 + 配置 */}
            <div className="preview-footer">
              <div className="preview-cost">
                预估费用: <strong>¥{previewResult.estimated_cost.toFixed(2)}</strong>
                <span className="preview-cost-hint">（以实际扣费为准）</span>
              </div>
              <div className="preview-config">
                {previewResult.ratio} · {previewResult.resolution} · {previewResult.duration}s
                {previewResult.generate_audio ? " · 含音频" : ""}
              </div>
            </div>
          </div>
        )}

        {/* A台生成进度 */}
        {composeRunning && (
          <div className="batch-progress">
            <div className="batch-progress-header"><span>{composeProgress}</span></div>
            <div className="progress-bar"><div className="progress-fill" style={{ width: "40%", animation: "load 1.4s infinite" }} /></div>
          </div>
        )}

        {/* B台裂变进度 */}
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

        {/* 源视频池状态 */}
        {currentSourceVideoIds.length > 0 && (
          <div style={{ marginTop: 10, fontSize: 12, color: "#64748b" }}>
            会话源视频池: {currentSourceVideoIds.length} 个（合格 {qualifiedCount} 个）
            {qualifiedCount >= 5 && <span> · 本轮最多使用前5个合格视频，预计生成50条</span>}
            {batchIgnored.length > 0 && <span style={{ color: "#f59e0b" }}> · 部分视频未参与本轮裂变</span>}
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
                    title="浏览器将保存到下载目录">{dlBtnText(v.video_id)}</button>
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
                    title="浏览器将保存到下载目录">{dlBtnText(v.video_id)}</button>
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
