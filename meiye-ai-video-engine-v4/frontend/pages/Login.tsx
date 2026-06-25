/**
 * 登录页 — 手机号 + 邀约码
 * 管理员后台入口：登录后根据 JWT role（/api/me）自动显示
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  login, getToken, fetchMe, getUserProfile,
} from "../api/client";

export default function Login() {
  const navigate = useNavigate();

  const [phone, setPhone] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3000); };

  // 已登录直接跳转（确保 /api/me 已获取）
  if (getToken()) {
    if (!getUserProfile()) fetchMe();
    navigate("/workbench", { replace: true });
    return null;
  }

  // ---- 登录处理 ----
  const handleLogin = async () => {
    if (!phone.trim()) { setError("请输入手机号"); return; }
    if (!inviteCode.trim()) { setError("请输入邀约码"); return; }
    setLoading(true);
    setError("");
    try {
      const r = await login(phone.trim(), inviteCode.trim());
      if (r.code === 0) {
        // 登录成功后立即调用 /api/me 获取用户角色
        const meR = await fetchMe();
        if (meR.code !== 0) {
          console.warn("/api/me 调用失败，将以普通用户身份进入", meR.message);
        }
        navigate("/workbench", { replace: true });
      } else {
        setError(r.message || `登录失败 (code: ${r.code})`);
      }
    } catch {
      setError("网络异常，请检查后端是否启动");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      {toast && <div className="toast">{toast}</div>}
      <div className="login-card">
        <div className="login-header">
          <h1>美业AI视频系统</h1>
          <p className="login-subtitle">V4.0 SaaS 工作台</p>
        </div>
        <div className="login-form">
          <label>手机号</label>
          <input type="tel" placeholder="请输入手机号" value={phone}
            onChange={(e) => setPhone(e.target.value)} disabled={loading} />
          <label>邀约码</label>
          <input type="text" placeholder="请输入邀约码" value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleLogin()} disabled={loading} />
          {error && <p className="login-error">{error}</p>}
          <button className="login-btn" onClick={handleLogin}
            disabled={loading || !navigator.onLine}>
            {loading ? "登录中..." : "进入系统"}
          </button>
        </div>
      </div>
    </div>
  );
}
