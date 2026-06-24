/**
 * API 绑定层 — 对照 docs/frontend_contract.md
 * 前端只通过 /api/* 访问后端。
 * 增强：token/tenant 持久化到 localStorage，统一错误处理。
 */

const BASE = "/api";

// ---- 租户 & Token 持久化 ----
const LS_TENANT = "v4_tenant_id";
const LS_TOKEN = "v4_token";

let TENANT = localStorage.getItem(LS_TENANT) || "default";
let TOKEN = localStorage.getItem(LS_TOKEN) || "";

export function setTenant(t: string) {
  TENANT = t || "default";
  localStorage.setItem(LS_TENANT, TENANT);
}
export function setToken(t: string) {
  TOKEN = t || "";
  localStorage.setItem(LS_TOKEN, TOKEN);
}
export function getTenant() {
  return TENANT;
}
export function getToken() {
  return TOKEN;
}
export function clearAuth() {
  TENANT = "default";
  TOKEN = "";
  localStorage.removeItem(LS_TENANT);
  localStorage.removeItem(LS_TOKEN);
}

// ---- 类型 ----
export interface Resp<T = unknown> {
  code: number;
  msg: string;
  data: T;
}

export interface VideoItem {
  video_id: number;
  type: "mother" | "viral";
  title: string;
  source_video_id: number | null;
  download_url: string;
  share_url: string;
  strategy?: string;
  store_id?: number;
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
  by_api: Record<string, number>;
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

// ---- 底层请求 ----
function headers(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    "X-Tenant-Id": TENANT,
    ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
  };
}

async function get<T = unknown>(path: string): Promise<Resp<T>> {
  const res = await fetch(`${BASE}${path}`, { headers: headers() });
  if (!res.ok) {
    return { code: -1, msg: `HTTP ${res.status}`, data: null as T };
  }
  return res.json();
}

async function post<T = unknown>(path: string, body: unknown): Promise<Resp<T>> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    return { code: -1, msg: `HTTP ${res.status}`, data: null as T };
  }
  return res.json();
}

// ---- 鉴权 ----
export async function login(phoneOrToken: string) {
  const r = await post<{ token: string; tenant_id: string }>("/auth/login", {
    phone: phoneOrToken,
  });
  if (r.code === 0 && r.data) {
    setTenant(r.data.tenant_id);
    setToken(r.data.token);
  }
  return r;
}

// ---- 一句话生成（统一入口，A台批量）----
export const intentPlan = (text: string) => post("/intent/plan", { text });

export const generate = (text: string) => post("/generate", { text });

// ---- A台 / B台（单条入口）----
export const aGenerate = (prompt: string, title?: string) =>
  post<{ task_id: string }>("/a/generate", { prompt, title });

export const bGenerate = (
  sourceVideoId: number,
  count = 10,
  strategy = "mix",
  prompt?: string,
) =>
  post<{ task_id: string }>("/b/generate", {
    source_video_id: sourceVideoId,
    count,
    strategy,
    prompt,
  });

export const strategies = () =>
  get<{ items: StrategyItem[] }>("/b/strategies");

// ---- 任务（轮询）----
export const getTask = (taskId: string) => get<TaskData>(`/tasks/${taskId}`);
export const listTasks = () =>
  get<{ items: TaskData[]; total: number }>("/tasks");
export const retryTask = (taskId: string) =>
  post(`/tasks/${taskId}/retry`, {});

/** 轮询直到 done/failed。onTick 可用于更新进度。 */
export async function pollTask(
  taskId: string,
  onTick?: (d: TaskData) => void,
  intervalMs = 1500,
): Promise<Resp<TaskData>> {
  for (;;) {
    const r = await getTask(taskId);
    const d = r.data;
    if (d) onTick?.(d);
    if (d?.status === "done" || d?.status === "failed" || r.code !== 0)
      return r;
    await new Promise((res) => setTimeout(res, intervalMs));
  }
}

// ---- 历史视频 ----
export const listVideos = (
  type: "mother" | "viral" = "mother",
  page = 1,
  pageSize = 20,
) => get<{ items: VideoItem[]; total: number }>(`/videos?type=${type}&page=${page}&page_size=${pageSize}`);

// ---- 门店 ----
export const listStores = () =>
  get<{ items: { store_id: number; name: string; city: string; industry: string }[] }>("/stores");

// ---- 成本 ----
export const costSummary = () => get<CostSummary>("/cost/summary");
export const costByStore = () => get<{ items: unknown[] }>("/cost/by-store");
export const costByProvider = () => get<{ items: unknown[] }>("/cost/by-provider");

// ---- 业务指标 ----
export const metricsOverview = () => get<MetricsOverview>("/metrics/overview");
export const metricsByStore = () => get<{ items: unknown[] }>("/metrics/by-store");
export const metricsByStrategy = () => get<{ items: unknown[] }>("/metrics/by-strategy");
