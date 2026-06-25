/**
 * 登录页 — 手机号 + 邀约码 + 管理员发码入口
 * 管理员面板不需要 JWT，仅需 ADMIN_KEY（sessionStorage）。
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  login, getToken,
  getAdminKey, setAdminKey, clearAdminKey,
  adminInviteGenerate, adminInviteList, adminInviteRevoke,
  type InviteItem,
} from "../api/client";

export default function Login() {
  const navigate = useNavigate();

  // ---- 登录 ----
  const [phone, setPhone] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // ---- 管理员 ----
  const [showAdmin, setShowAdmin] = useState(false);
  const [adminKey, setAdminKeyState] = useState(getAdminKey());
  const [keyInput, setKeyInput] = useState("");
  const [keyError, setKeyError] = useState("");
  const [count, setCount] = useState(1);
  const [maxUses, setMaxUses] = useState(1);
  const [note, setNote] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generatedCodes, setGeneratedCodes] = useState<InviteItem[]>([]);
  const [invites, setInvites] = useState<InviteItem[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [toast, setToast] = useState("");

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3000); };

  // 已登录直接跳转
  if (getToken() && !showAdmin) {
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

  // ---- 管理员密钥验证 ----
  const handleSetKey = async () => {
    if (!keyInput.trim()) { setKeyError("请输入管理员密钥"); return; }
    setAdminKey(keyInput.trim());
    setAdminKeyState(keyInput.trim());
    setKeyError("");
    setListLoading(true);
    const r = await adminInviteList();
    if (r.code !== 0) {
      clearAdminKey();
      setAdminKeyState("");
      setKeyError("管理员密钥无效，请重新输入");
    } else {
      setInvites(r.data?.items || []);
      showToast("密钥验证通过");
    }
    setListLoading(false);
  };

  // ---- 生成邀请码 ----
  const handleGenerate = async () => {
    setGenerating(true);
    setGeneratedCodes([]);
    const r = await adminInviteGenerate(count, maxUses, note || undefined);
    if (r.code === 0 && r.data) {
      setGeneratedCodes(r.data.items || []);
      showToast(`成功生成 ${r.data.count} 个邀请码`);
      // 刷新列表
      const lr = await adminInviteList();
      if (lr.code === 0) setInvites(lr.data?.items || []);
    } else {
      showToast(r.message || "生成失败");
    }
    setGenerating(false);
  };

  // ---- 作废 ----
  const handleRevoke = async (code: string) => {
    if (!confirm(`确定作废邀请码 ${code}？作废后不可恢复。`)) return;
    const r = await adminInviteRevoke(code);
    if (r.code === 0) {
      showToast(`邀请码 ${code} 已作废`);
      const lr = await adminInviteList();
      if (lr.code === 0) setInvites(lr.data?.items || []);
    } else {
      showToast(r.message || "作废失败");
    }
  };

  // ---- 复制 ----
  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text).then(
      () => showToast(`已复制: ${text}`),
      () => showToast("复制失败，请手动复制"),
    );
  };

  // ---- 退出管理 ----
  const handleExitAdmin = () => {
    clearAdminKey();
    setAdminKeyState("");
    setShowAdmin(false);
    setInvites([]);
    setGeneratedCodes([]);
  };

  // ===========================================================
  // 管理员面板（无 JWT 也可使用）
  // ===========================================================
  if (showAdmin) {
    // 未输入密钥
    if (!adminKey) {
      return (
        <div className="login-page">
          {toast && <div className="toast">{toast}</div>}
          <div className="login-card admin-key-card">
            <h1>管理员发码</h1>
            <p className="admin-hint">请输入管理员密钥（ADMIN_KEY）</p>
            <input type="password" placeholder="管理员密钥"
              value={keyInput} onChange={(e) => setKeyInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSetKey()} />
            {keyError && <p className="login-error">{keyError}</p>}
            <div className="admin-key-actions">
              <button className="login-btn" onClick={handleSetKey}>验证密钥</button>
              <button className="btn" onClick={() => setShowAdmin(false)}>返回登录</button>
            </div>
          </div>
        </div>
      );
    }

    // 管理面板
    return (
      <div className="login-page admin-embedded">
        {toast && <div className="toast">{toast}</div>}
        <div className="admin-panel-embedded">
          <header className="admin-header">
            <h1>邀约码管理</h1>
            <div className="admin-header-actions">
              <button className="btn" onClick={async () => {
                setListLoading(true);
                const r = await adminInviteList();
                if (r.code === 0) setInvites(r.data?.items || []);
                setListLoading(false);
              }}>刷新</button>
              <button className="btn" onClick={handleExitAdmin}>返回登录</button>
            </div>
          </header>

          {/* 生成 */}
          <section className="admin-section">
            <h2>生成邀请码</h2>
            <div className="admin-form">
              <div className="admin-form-row">
                <label>数量</label>
                <input type="number" min={1} max={100} value={count}
                  onChange={(e) => setCount(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))} />
              </div>
              <div className="admin-form-row">
                <label>最大使用次数</label>
                <input type="number" min={1} max={100000} value={maxUses}
                  onChange={(e) => setMaxUses(Math.max(1, parseInt(e.target.value) || 1))} />
              </div>
              <div className="admin-form-row">
                <label>备注</label>
                <input type="text" placeholder="如：给XX客户" value={note}
                  onChange={(e) => setNote(e.target.value)} />
              </div>
              <button className="login-btn" onClick={handleGenerate} disabled={generating}
                style={{ padding: "8px 18px", width: "auto" }}>
                {generating ? "生成中..." : "生成邀请码"}
              </button>
            </div>

            {generatedCodes.length > 0 && (
              <div className="generated-codes">
                <h3>新生成的邀请码（请复制后发给客户）</h3>
                {generatedCodes.map((item) => (
                  <div key={item.code} className="generated-code-item">
                    <code className="code-value">{item.code}</code>
                    <button className="btn btn-sm" onClick={() => handleCopy(item.code)}>复制</button>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* 列表 */}
          <section className="admin-section">
            <h2>邀请码列表（{invites.length} 条）</h2>
            {listLoading ? <p>加载中...</p> : invites.length === 0 ? (
              <p className="empty-state">暂无邀请码</p>
            ) : (
              <div className="admin-table-wrap">
                <table className="task-table admin-table">
                  <thead>
                    <tr>
                      <th>邀请码</th>
                      <th>备注</th>
                      <th>绑定手机号</th>
                      <th>已用/上限</th>
                      <th>状态</th>
                      <th>创建时间</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invites.map((item) => (
                      <tr key={item.code} className={!item.active ? "revoked-row" : ""}>
                        <td>
                          <code className="code-value">{item.code}</code>
                          <button className="btn-copy" onClick={() => handleCopy(item.code)} title="复制">📋</button>
                        </td>
                        <td>{item.note || "-"}</td>
                        <td>{item.phone || "-"}</td>
                        <td>{item.used_count ?? 0} / {item.max_uses ?? 1}</td>
                        <td>
                          <span className={`tag ${item.active ? "tag-done" : "tag-failed"}`}>
                            {item.active ? "有效" : "已作废"}
                          </span>
                        </td>
                        <td>{item.created_at ? new Date(item.created_at).toLocaleString("zh-CN") : "-"}</td>
                        <td>
                          {item.active && (
                            <button className="btn btn-sm btn-error" onClick={() => handleRevoke(item.code)}>作废</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>
    );
  }

  // ===========================================================
  // 普通登录页
  // ===========================================================
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
        <div className="login-admin-entry">
          <button className="btn-admin-link" onClick={() => setShowAdmin(true)}>
            管理员发码
          </button>
        </div>
      </div>
    </div>
  );
}
