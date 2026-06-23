// 前端 API 调用层（skeleton）。前端只通过 /api/* 与后端通信。
const BASE = "/api";

async function post(path: string, body: unknown) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

export const login = (phoneOrToken: string) => post("/auth/login", { phone: phoneOrToken });
export const generateMother = (prompt: string) => post("/a/generate", { prompt });
export const generateViral = (prompt: string) => post("/b/generate", { prompt });
export const getTask = (taskId: string) => fetch(`${BASE}/tasks/${taskId}`).then((r) => r.json());
export const listVideos = (type: "mother" | "viral") =>
  fetch(`${BASE}/videos?type=${type}`).then((r) => r.json());
