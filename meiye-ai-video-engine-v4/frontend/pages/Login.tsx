/**
 * 登录页 — 手机号 + 邀约码（Patch4）。
 * 同一手机号可用同一邀约码重复登录（Patch4.1 修复）。
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login, getToken } from "../api/client";

export default function Login() {
  const [phone, setPhone] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const navigate = useNavigate();

  // 已登录直接跳转
  if (getToken()) {
    navigate("/workbench", { replace: true });
    return null;
  }

  const handleLogin = async () => {
    if (!phone.trim()) { setError("请输入手机号"); return; }
    if (!inviteCode.trim()) { setError("请输入邀约码"); return; }

    setLoading(true);
    setError("");
    try {
      const r = await login(phone.trim(), inviteCode.trim());
      if (r.code === 0) {
        navigate("/workbench", { replace: true });
      } else if (r.code === 4010) {
        setError("该邀请码已绑定其他手机号");
      } else {
        setError(r.message || "登录失败");
      }
    } catch {
      setError("网络异常，请检查后端是否启动");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <h1>美业AI视频系统</h1>
          <p className="login-subtitle">V4.0 SaaS 工作台</p>
        </div>
        <div className="login-form">
          <label>手机号</label>
          <input
            type="tel"
            placeholder="请输入手机号"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            disabled={loading}
          />
          <label>邀约码</label>
          <input
            type="text"
            placeholder="请输入邀约码"
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleLogin()}
            disabled={loading}
          />
          {error && <p className="login-error">{error}</p>}
          <button
            className="login-btn"
            onClick={handleLogin}
            disabled={loading || !navigator.onLine}
          >
            {loading ? "登录中..." : "进入系统"}
          </button>
        </div>
      </div>
    </div>
  );
}
