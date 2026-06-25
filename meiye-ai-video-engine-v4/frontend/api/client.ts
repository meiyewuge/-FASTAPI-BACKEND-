/**
 * API 绑定层 — V4 前端联调版（对齐 claude/v4-staging Patch1~Patch5+Patch4.1）
 *
 * 端点清单：
 *   POST /auth/login  (phone + invite_code → JWT)
 *   POST /generate, /a/generate, /b/generate, /compose
 *   GET  /b/strategies
 *   GET  /tasks/{id}, /tasks
 *   POST /tasks/{id}/retry
 *   GET  /videos, /videos/{id}/url
 *   POST /upload (image/text/video)
 *   POST /export (csv/json), /export/videos (mp4 URL list)
 *   GET  /cost/summary, /metrics/overview, /subscription/status
 *
 * 鉴权：Authorization: Bearer <JWT>（无 X-Tenant-Id）
 * 401 → 自动清 token + 跳登录
 * 响应字段：{ code, message, data }（与后端 Resp 一致）
 */

const BASE = "/api";

// ---- JWT 持久化 ----
const LS_TOKEN = "v4_jwt";
const LS_TENANT = "v4_tenant_id";

let TOKEN = localStorage.getItem(LS_TOKEN) || "";
let TENANT = localStorage.getItem(LS_TENANT) || "";

export function setToken(t: string) { TOKEN = t; localStorage.setItem(LS_TOKEN, t); }
export function setTenant(t: string) { TENANT = t; localStorage.setItem(LS_TENANT, t); }
export function getToken() { return TOKEN; }
export function getTenant() { return TENANT; }
export function clearAuth() {
  TOKEN = ""; TENANT = "";
  localStorage.removeItem(LS_TOKEN);
  localStorage.removeItem(LS_TENANT);
}

// 401 回调：由 main.tsx 注入 router navigate
let _on401: (() => void) | null = null;
export function register401(cb: () => void) { _on401 = cb; }

// ---- 类型（与后端 Resp 对齐）----
export interface Resp<T = unknown> {
  code: number;
  message: string;
  data: T;
}

export interface VideoItem {
  video_id: number;
  type: "mother" | "viral" | "source";
  title: string;
  source_video_id: number | null;
  download_url: string;
  share_url: string;
  cover_url?: string;
  strategy?: string;
  store_id?: number;
  duration?: number;
  file_size?: number;
  source?: string;
  created_at?: string;
  storage_expires_at?: string;
  days_remaining?: number;
  status?: string;
}

export interface TaskData {
  task_id: string;
  type: "a" | "b";
  status: "pending" | "running" | "done" | "failed";
  progress: number;
  retry_count: number;
  error: string | null;
  result: { videos: VideoItem[] } | null;
}

export interface CostSummary {
  tenant_id: string;
  quota: number;
  spend: number;
  remaining: number;
  by_api?: Record<string, number>;
}

export interface StrategyItem {
  key: string;
  label: string;
  goal: string;
  cta: string;
}

export interface MetricsOverview {
  total_videos: number;
  total_cost: number;
  videos_per_cost_unit: number;
  remix_multiplier: number;
}

export interface SubscriptionStatus {
  plan: string;
  trial_remaining: number;
  quota_remaining: number;
}

export interface UploadResult {
  file_id: number;
  file_url: string;
  file_type: string;
  file_name: string;
  file_size: number;
}

export interface ExportParams {
  video_ids?: number[];
  type?: "mother" | "viral";
  strategy?: string;
  store_id?: number;
  source_video_id?: number;
  format?: "json" | "csv";
}

// ---- 底层请求 ----
function authHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
  };
}

/** 统一 401 检测 */
function check401(res: Response) {
  if (res.status === 401) {
    clearAuth();
    _on401?.();
  }
}

async function get<T = unknown>(path: string): Promise<Resp<T>> {
  try {
    const res = await fetch(`${BASE}${path}`, { headers: authHeaders() });
    check401(res);
    if (!res.ok) return { code: -1, message: `HTTP ${res.status}`, data: null as T };
    return res.json();
  } catch {
    return { code: -1, message: !navigator.onLine ? "网络连接已断开" : "网络异常", data: null as T };
  }
}

async function post<T = unknown>(path: string, body: unknown): Promise<Resp<T>> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body),
    });
    check401(res);
    if (!res.ok) return { code: -1, message: `HTTP ${res.status}`, data: null as T };
    return res.json();
  } catch {
    return { code: -1, message: !navigator.onLine ? "网络连接已断开" : "网络异常", data: null as T };
  }
}

// ---- 鉴权（Patch4：手机号 + 邀约码）----
export async function login(phone: string, inviteCode: string) {
  const r = await post<{ token: string; tenant_id: string }>("/auth/login", {
    phone,
    invite_code: inviteCode,
  });
  if (r.code === 0 && r.data) {
    setToken(r.data.token);
    setTenant(r.data.tenant_id);
  }
  return r;
}

// ---- 生成 ----
export const generate = (text: string) =>
  post<{ plan?: { task_ids?: string[] } }>("/generate", { text });

export const aGenerate = (prompt: string, title?: string, duration?: number, resolution?: string) =>
  post<{ task_id: string }>("/a/generate", { prompt, title, duration, resolution });

export const bGenerate = (
  sourceVideoId: number, count = 10, strategy = "mix", prompt?: string,
) =>
  post<{ task_id: string }>("/b/generate", {
    source_video_id: sourceVideoId, count, strategy, prompt,
  });

export const compose = (prompt: string, totalSeconds = 30, resolution = "720p", title?: string) =>
  post<{ task_id: string }>("/compose", {
    prompt, total_seconds: totalSeconds, resolution, title,
  });

export const strategies = () =>
  get<{ items: StrategyItem[] }>("/b/strategies");

// ---- 任务 ----
export const getTask = (taskId: string) => get<TaskData>(`/tasks/${taskId}`);
export const listTasks = () => get<{ items: TaskData[]; total: number }>("/tasks");
export const retryTask = (taskId: string) => post(`/tasks/${taskId}/retry`, {});

export async function pollTask(
  taskId: string, onTick?: (d: TaskData) => void, intervalMs = 2000,
): Promise<Resp<TaskData>> {
  for (;;) {
    const r = await getTask(taskId);
    const d = r.data;
    if (d) onTick?.(d);
    if (d?.status === "done" || d?.status === "failed" || r.code !== 0) return r;
    await new Promise((res) => setTimeout(res, intervalMs));
  }
}

// ---- 视频 ----
export const listVideos = (type: "mother" | "viral" = "mother", page = 1, pageSize = 20) =>
  get<{ items: VideoItem[]; total: number }>(
    `/videos?type=${type}&page=${page}&page_size=${pageSize}`,
  );

/** 刷新视频 URL（CDN 签名过期时用）*/
export const refreshVideoUrl = (videoId: number) =>
  get<{ video_id: number; download_url: string; share_url: string }>(`/videos/${videoId}/url`);

// ---- 上传（Patch2）----
export async function uploadFile(
  type: "image" | "text" | "video",
  file: File | null,
  content?: string,
  onProgress?: (pct: number) => void,
): Promise<Resp<UploadResult>> {
  const form = new FormData();
  form.append("type", type);
  if (file) form.append("file", file);
  if (content !== undefined) form.append("content", content);

  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/upload`);
    if (TOKEN) xhr.setRequestHeader("Authorization", `Bearer ${TOKEN}`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status === 401) { clearAuth(); _on401?.(); }
      try {
        resolve(JSON.parse(xhr.responseText));
      } catch {
        resolve({ code: -1, message: `HTTP ${xhr.status}`, data: null as unknown as UploadResult });
      }
    };
    xhr.onerror = () => {
      resolve({ code: -1, message: "网络异常", data: null as unknown as UploadResult });
    };
    xhr.send(form);
  });
}

// ---- 成本 ----
export const costSummary = () => get<CostSummary>("/cost/summary");
export const metricsOverview = () => get<MetricsOverview>("/metrics/overview");
export const subscriptionStatus = () => get<SubscriptionStatus>("/subscription/status");

// ---- 导出 ----
/** CSV 元数据导出（浏览器下载） */
export async function exportVideosCSV(params: ExportParams): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/export`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ ...params, format: "csv" }),
    });
    if (res.status === 401) { clearAuth(); _on401?.(); return false; }
    if (!res.ok) return false;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `视频导出_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    return true;
  } catch {
    return false;
  }
}

/** JSON 元数据导出 */
export const exportVideosJSON = (params: ExportParams) =>
  post<{ count: number; items: unknown[] }>("/export", { ...params, format: "json" });

/** 视频 mp4 URL 导出（Patch3 方案B） */
export const exportVideosMp4 = (params: ExportParams) =>
  post<{ count: number; videos: { video_id: number; title: string; download_url: string }[] }>(
    "/export/videos", params,
  );

// ---- 稳定下载（AbortController + 30s超时 + 重试 + URL刷新）----
export async function stableDownload(
  video: { video_id: number; download_url: string; title?: string },
  onProgress?: (pct: number) => void,
): Promise<{ ok: boolean; error?: string }> {
  const maxRetries = 2;
  let url = video.download_url;

  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 30000); // 30s

      const resp = await fetch(url, { signal: controller.signal });
      clearTimeout(timeout);

      if (!resp.ok) {
        // CDN URL 可能过期 → 刷新后重试
        if ((resp.status === 403 || resp.status === 404) && attempt === 0) {
          const refreshed = await refreshVideoUrl(video.video_id);
          if (refreshed.code === 0 && refreshed.data?.download_url) {
            url = refreshed.data.download_url;
            continue; // 用新 URL 重试
          }
        }
        return { ok: false, error: `HTTP ${resp.status}` };
      }

      // 读取 blob（带进度）
      const contentLength = Number(resp.headers.get("content-length")) || 0;
      const reader = resp.body?.getReader();
      if (!reader) return { ok: false, error: "无法读取响应" };

      const chunks: Uint8Array[] = [];
      let loaded = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        loaded += value.length;
        if (contentLength > 0 && onProgress) {
          onProgress(Math.round((loaded / contentLength) * 100));
        }
      }

      const blob = new Blob(chunks as unknown as BlobPart[], { type: "video/mp4" });
      const blobUrl = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = `${video.title || `视频_${video.video_id}`}.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
      return { ok: true };
    } catch (e: unknown) {
      if (attempt < maxRetries - 1) {
        // URL 可能过期，先刷新再重试
        const refreshed = await refreshVideoUrl(video.video_id);
        if (refreshed.code === 0 && refreshed.data?.download_url) {
          url = refreshed.data.download_url;
          continue;
        }
      }
      const msg = e instanceof Error && e.name === "AbortError" ? "下载超时（30s）" : "下载失败";
      return { ok: false, error: msg };
    }
  }
  return { ok: false, error: "下载失败" };
}

// ===========================================================================
// 管理员权限 — JWT role 模式（Patch6 已上线）
// A. 正式模式：JWT Bearer + GET /api/me role（当前默认）
// B. 临时 fallback：X-Admin-Key（仅紧急回退用，默认关闭）
// ===========================================================================
export const ENABLE_ADMIN_KEY_FALLBACK = false; // ← Patch6 已上线，关闭临时模式

const SS_ADMIN_KEY = "v4_admin_key";

export function getAdminKey(): string {
  return sessionStorage.getItem(SS_ADMIN_KEY) || "";
}
export function setAdminKey(key: string) {
  sessionStorage.setItem(SS_ADMIN_KEY, key);
}
export function clearAdminKey() {
  sessionStorage.removeItem(SS_ADMIN_KEY);
}

// ---- 角色类型（对齐后端 Patch6 /api/me）----
export type UserRole = "super_admin" | "invite_admin" | "user";

export interface UserProfile {
  phone: string;
  tenant_id: string;
  role: UserRole;
  is_admin: boolean;
  permissions: string[];
}

let _userProfile: UserProfile | null = null;

export function setUserProfile(p: UserProfile | null) { _userProfile = p; }
export function getUserProfile(): UserProfile | null { return _userProfile; }

/** 当前用户角色（优先 _userProfile，fallback 到 ADMIN_KEY（仅当开关开启时）） */
export function getCurrentUserRole(): UserRole {
  if (_userProfile) return _userProfile.role;
  if (ENABLE_ADMIN_KEY_FALLBACK && getAdminKey()) return "super_admin";
  return "user";
}

/** 是否有管理员权限 */
export function isAdmin(): boolean {
  const role = getCurrentUserRole();
  return role === "super_admin" || role === "invite_admin";
}

/** 是否为超级管理员 */
export function isSuperAdmin(): boolean {
  return getCurrentUserRole() === "super_admin";
}

// ---- /api/me ----
export async function fetchMe(): Promise<Resp<UserProfile>> {
  const r = await get<UserProfile>("/me");
  if (r.code === 0 && r.data) {
    _userProfile = r.data;
  }
  return r;
}

// ---- 管理员请求头（纯 JWT，fallback 关闭时不带 X-Admin-Key）----
function adminHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (TOKEN) headers["Authorization"] = `Bearer ${TOKEN}`;
  // 仅在 fallback 开启时才附加 X-Admin-Key
  if (ENABLE_ADMIN_KEY_FALLBACK && getAdminKey()) {
    headers["X-Admin-Key"] = getAdminKey();
  }
  return headers;
}

async function adminPost<T = unknown>(path: string, body: unknown): Promise<Resp<T>> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: adminHeaders(),
      body: JSON.stringify(body),
    });
    check401(res);
    if (res.status === 403) {
      return { code: -1, message: "权限不足，仅管理员可操作", data: null as unknown as T };
    }
    if (!res.ok) return { code: -1, message: `HTTP ${res.status}`, data: null as unknown as T };
    return res.json();
  } catch {
    return { code: -1, message: "网络异常", data: null as unknown as T };
  }
}

async function adminGet<T = unknown>(path: string): Promise<Resp<T>> {
  try {
    const res = await fetch(`${BASE}${path}`, { headers: adminHeaders() });
    check401(res);
    if (res.status === 403) {
      return { code: -1, message: "权限不足，仅管理员可操作", data: null as unknown as T };
    }
    if (!res.ok) return { code: -1, message: `HTTP ${res.status}`, data: null as unknown as T };
    return res.json();
  } catch {
    return { code: -1, message: "网络异常", data: null as unknown as T };
  }
}

// ---- 管理员：邀约码管理 ----
export interface InviteItem {
  code: string;
  tenant_id: string | null;
  phone: string | null;
  used_count: number;
  max_uses: number;
  note: string | null;
  active: boolean;
  created_at: string;
}

export const adminInviteGenerate = (
  count: number, maxUses: number, note?: string, tenantId?: string,
) =>
  adminPost<{ items: InviteItem[]; count: number }>("/admin/invite/generate", {
    count, max_uses: maxUses, note, tenant_id: tenantId,
  });

export const adminInviteList = () =>
  adminGet<{ items: InviteItem[]; total: number }>("/admin/invite/list");

export const adminInviteRevoke = (code: string) =>
  adminPost<{ code: string; active: boolean }>("/admin/invite/revoke", { code });

// ---- 管理员：用户授权管理（Patch6 新增）----
export interface AdminUserItem {
  phone: string;
  tenant_id: string;
  role: UserRole;
  is_admin: boolean;
  granted_at?: string;
}

/** 授权员工为 invite_admin */
export const adminGrantUser = (phone: string, role: UserRole = "invite_admin") =>
  adminPost<{ phone: string; role: UserRole }>("/admin/users/grant", { phone, role });

/** 取消员工管理员权限 */
export const adminRevokeUser = (phone: string) =>
  adminPost<{ phone: string; role: string }>("/admin/users/revoke", { phone });

/** 查看管理员列表 */
export const adminListUsers = () =>
  adminGet<{ items: AdminUserItem[]; total: number }>("/admin/users/list");

// ===========================================================================
// V4 页面重构 — 新增端点（Claude P0 主干 + 回流层）
// ===========================================================================

// ---- 底层 DELETE 请求 ----
async function del<T = unknown>(path: string): Promise<Resp<T>> {
  try {
    const res = await fetch(`${BASE}${path}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    check401(res);
    if (!res.ok) return { code: -1, message: `HTTP ${res.status}`, data: null as T };
    return res.json();
  } catch {
    return { code: -1, message: !navigator.onLine ? "网络连接已断开" : "网络异常", data: null as T };
  }
}

// ---- 批量上传 ----
export interface BatchUploadItem {
  file_id: number;
  file_url: string;
  file_type: string;
  file_name: string;
  file_size: number;
  status: "ok" | "failed";
  error?: string;
}

/**
 * 批量上传文件 — POST /uploads/batch (FormData)
 * type: image | video | file
 * 失败文件不影响其他文件展示
 */
export async function batchUpload(
  files: File[],
  type: "image" | "video" | "file",
  onProgress?: (pct: number) => void,
): Promise<Resp<{ items: BatchUploadItem[]; total: number; ok_count: number; failed_count: number }>> {
  const form = new FormData();
  form.append("type", type);
  files.forEach((f) => form.append("files", f));

  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${BASE}/uploads/batch`);
    if (TOKEN) xhr.setRequestHeader("Authorization", `Bearer ${TOKEN}`);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status === 401) { clearAuth(); _on401?.(); }
      try {
        resolve(JSON.parse(xhr.responseText));
      } catch {
        resolve({ code: -1, message: `HTTP ${xhr.status}`, data: null as unknown as { items: BatchUploadItem[]; total: number; ok_count: number; failed_count: number } });
      }
    };
    xhr.onerror = () => {
      resolve({ code: -1, message: "网络异常", data: null as unknown as { items: BatchUploadItem[]; total: number; ok_count: number; failed_count: number } });
    };
    xhr.send(form);
  });
}

// ---- B台批量裂变 ----
export interface BatchGenerateResult {
  batch_id: string;
  status: "pending" | "running" | "done" | "failed";
  source_count: number;
  total_outputs: number;
}

export interface BatchStatusItem {
  video_id: number;
  source_video_id: number;
  status: "pending" | "running" | "done" | "failed";
  download_url?: string;
}

export interface BatchStatus {
  batch_id: string;
  status: "pending" | "running" | "done" | "failed";
  completed: number;
  total_outputs: number;
  failed: number;
  items: BatchStatusItem[];
}

/** B台批量裂变 — POST /b/batch-generate */
export const batchGenerate = (
  sourceVideoIds: number[], count: number, strategy = "mix", prompt?: string,
) =>
  post<BatchGenerateResult>("/b/batch-generate", {
    source_video_ids: sourceVideoIds,
    count,
    strategy,
    prompt,
  });

/** B台批量状态轮询 — GET /b/batch/{batchId} */
export const getBatchStatus = (batchId: string) =>
  get<BatchStatus>(`/b/batch/${batchId}`);

/** B台批量轮询（异步，不阻塞页面） */
export async function pollBatchStatus(
  batchId: string,
  onTick?: (d: BatchStatus) => void,
  intervalMs = 3000,
): Promise<Resp<BatchStatus>> {
  for (;;) {
    const r = await getBatchStatus(batchId);
    const d = r.data;
    if (d) onTick?.(d);
    if (d?.status === "done" || d?.status === "failed" || r.code !== 0) return r;
    await new Promise((res) => setTimeout(res, intervalMs));
  }
}

// ---- 删除视频 ----
/** DELETE /videos/{videoId} */
export const deleteVideo = (videoId: number) =>
  del<{ video_id: number; deleted: boolean }>(`/videos/${videoId}`);

// ---- 存储状态 ----
export interface StorageStatus {
  scope: "tenant" | "global";
  mother_count: number;
  viral_count: number;
  upload_count: number;
  estimated_used_mb: number;
  disk_used_percent?: number;
  tenant_summary?: { tenant_id: string; count: number }[];
}

/** GET /storage/status */
export const storageStatus = () => get<StorageStatus>("/storage/status");

// ---- 事件埋点（失败不阻断） ----
/**
 * POST /events/track — 埋点接口，失败仅 console.warn
 */
export async function trackEvent(
  event: string,
  payload: Record<string, unknown> = {},
): Promise<void> {
  try {
    await post("/events/track", { event, ...payload });
  } catch (e) {
    console.warn(`[trackEvent] ${event} 埋点失败:`, e);
  }
}

// ---- 视频反馈 ----
/** POST /videos/{videoId}/feedback */
export const videoFeedback = (
  videoId: number, action: "favorite" | "useful" | "useless" | "note", note?: string,
) =>
  post<{ video_id: number; action: string }>(`/videos/${videoId}/feedback`, { action, note });

// ---- 管理员：候选池 ----
export interface KnowledgeCandidate {
  id: number;
  title: string;
  source: string;
  type: string;
  tags: string[];
  status: "pending" | "approved" | "rejected";
  created_at: string;
  video_id?: number;
}

/** GET /admin/knowledge-candidates */
export const adminListCandidates = () =>
  adminGet<{ items: KnowledgeCandidate[]; total: number }>("/admin/knowledge-candidates");

/** POST /admin/knowledge-candidates/{id}/approve */
export const adminApproveCandidate = (id: number) =>
  adminPost<{ id: number; status: string }>(`/admin/knowledge-candidates/${id}/approve`, {});

/** POST /admin/knowledge-candidates/{id}/reject */
export const adminRejectCandidate = (id: number) =>
  adminPost<{ id: number; status: string }>(`/admin/knowledge-candidates/${id}/reject`, {});
