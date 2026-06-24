// 前端 API 绑定层（对照 docs/frontend_contract.md）。前端只通过 /api/* 访问后端。
// 仅为「契约绑定」，不含 UI；Qoder 可直接用或参照改造。

const BASE = "/api";

// 登录后存租户，所有请求带 X-Tenant-Id
let TENANT = "default";
export function setTenant(t: string) {
  TENANT = t || "default";
}

interface Resp<T = any> {
  code: number; // 0 = 成功
  message: string;
  data: T;
}

function headers(): Record<string, string> {
  return { "Content-Type": "application/json", "X-Tenant-Id": TENANT };
}

async function get<T = any>(path: string): Promise<Resp<T>> {
  return (await fetch(`${BASE}${path}`, { headers: headers() })).json();
}
async function post<T = any>(path: string, body: unknown): Promise<Resp<T>> {
  return (
    await fetch(`${BASE}${path}`, { method: "POST", headers: headers(), body: JSON.stringify(body) })
  ).json();
}

// ---- 鉴权 ----
export async function login(phoneOrToken: string) {
  const r = await post("/auth/login", { phone: phoneOrToken });
  if (r.code === 0 && r.data?.tenant_id) setTenant(r.data.tenant_id);
  return r;
}

// ---- 一句话生成（统一入口，A台批量）----
export const intentPlan = (text: string) => post("/intent/plan", { text });
export const generate = (text: string) => post("/generate", { text });

// ---- A台 / B台（单条）----
export const aGenerate = (prompt: string, title?: string) => post("/a/generate", { prompt, title });
export const bGenerate = (sourceVideoId: number, count = 10, strategy = "mix", prompt?: string) =>
  post("/b/generate", { source_video_id: sourceVideoId, count, strategy, prompt });
export const strategies = () => get("/b/strategies");

// ---- 任务（轮询）----
export const getTask = (taskId: string) => get(`/tasks/${taskId}`);
export const listTasks = () => get("/tasks");
export const retryTask = (taskId: string) => post(`/tasks/${taskId}/retry`, {});

/** 轮询直到 done/failed。onTick 可用于更新进度。 */
export async function pollTask(taskId: string, onTick?: (d: any) => void, intervalMs = 1500) {
  for (;;) {
    const r = await getTask(taskId);
    const d = r.data;
    onTick?.(d);
    if (d?.status === "done" || d?.status === "failed" || r.code !== 0) return r;
    await new Promise((res) => setTimeout(res, intervalMs));
  }
}

// ---- 历史 / 门店 ----
export const listVideos = (type: "mother" | "viral" = "mother", page = 1, pageSize = 20) =>
  get(`/videos?type=${type}&page=${page}&page_size=${pageSize}`);
export const listStores = () => get("/stores");

// ---- 成本 ----
export const costSummary = () => get("/cost/summary");
export const costByStore = () => get("/cost/by-store");
export const costByProvider = () => get("/cost/by-provider");

// ---- 业务指标 ----
export const metricsOverview = () => get("/metrics/overview");
export const metricsByStore = () => get("/metrics/by-store");
export const metricsByStrategy = () => get("/metrics/by-strategy");
