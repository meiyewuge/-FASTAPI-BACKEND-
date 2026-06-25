/**
 * 管理员邀约码管理页 — P0 发码后台
 * ADMIN_KEY 仅存 sessionStorage，页面刷新后需重新输入。
 */
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  getAdminKey, setAdminKey, clearAdminKey,
  adminInviteGenerate, adminInviteList, adminInviteRevoke,
  type InviteItem, getToken,
} from "../api/client";

export default function AdminPanel() {
  const navigate = useNavigate();
  const [adminKey, setAdminKeyState] = useState(getAdminKey());
  const [keyInput, setKeyInput] = useState("");
  const [keyError, setKeyError] = useState("");

  // 生成表单
  const [count, setCount] = useState(1);
  const [maxUses, setMaxUses] = useState(1);
  const [note, setNote] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generatedCodes, setGeneratedCodes] = useState<InviteItem[]>([]);

  // 列表
  const [invites, setInvites] = useState<InviteItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState("");

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3000); };

  // 未登录跳回
  useEffect(() => {
    if (!getToken()) navigate("/login", { replace: true });
  }, [navigate]);

  // 加载列表
  const loadList = useCallback(async () => {
    if (!getAdminKey()) return;
    setLoading(true);
    const r = await adminInviteList();
    if (r.code === 0 && r.data) {
      setInvites(r.data.items || []);
    } else {
      setKeyError(r.message || "加载失败");
      clearAdminKey();
      setAdminKeyState("");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (adminKey) loadList();
  }, [adminKey, loadList]);

  // 验证密钥
  const handleSetKey = async () => {
    if (!keyInput.trim()) { setKeyError("请输入管理员密钥"); return; }
    setAdminKey(keyInput.trim());
    setAdminKeyState(keyInput.trim());
    setKeyError("");
    // 立即验证
    setLoading(true);
    const r = await adminInviteList();
    if (r.code !== 0) {
      clearAdminKey();
      setAdminKeyState("");
      setKeyError("管理员密钥无效，请重新输入");
    } else {
      setInvites(r.data?.items || []);
      showToast("密钥验证通过");
    }
    setLoading(false);
  };

  // 生成邀请码
  const handleGenerate = async () => {
    setGenerating(true);
    setGeneratedCodes([]);
    const r = await adminInviteGenerate(count, maxUses, note || undefined);
    if (r.code === 0 && r.data) {
      setGeneratedCodes(r.data.items || []);
      showToast(`成功生成 ${r.data.count} 个邀请码`);
      loadList();
    } else {
      showToast(r.message || "生成失败");
    }
    setGenerating(false);
  };

  // 作废
  const handleRevoke = async (code: string) => {
    if (!confirm(`确定作废邀请码 ${code}？作废后不可恢复。`)) return;
    const r = await adminInviteRevoke(code);
    if (r.code === 0) {
      showToast(`邀请码 ${code} 已作废`);
      loadList();
    } else {
      showToast(r.message || "作废失败");
    }
  };

  // 复制
  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text).then(
      () => showToast(`已复制: ${text}`),
      () => showToast("复制失败，请手动复制"),
    );
  };

  // 退出管理员
  const handleExit = () => {
    clearAdminKey();
    navigate("/workbench", { replace: true });
  };

  // ---- 未输入密钥：显示密钥输入页 ----
  if (!adminKey) {
    return (
      <div className="admin-page">
        <div className="admin-key-card">
          <h1>管理员入口</h1>
          <p className="admin-hint">请输入管理员密钥（ADMIN_KEY）</p>
          <input
            type="password"
            placeholder="管理员密钥"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSetKey()}
          />
          {keyError && <p className="login-error">{keyError}</p>}
          <div className="admin-key-actions">
            <button className="btn btn-primary" onClick={handleSetKey}>验证密钥</button>
            <button className="btn" onClick={() => navigate("/workbench", { replace: true })}>返回工作台</button>
          </div>
        </div>
      </div>
    );
  }

  // ---- 管理面板 ----
  return (
    <div className="admin-page">
      {toast && <div className="toast">{toast}</div>}

      <header className="admin-header">
        <h1>邀约码管理</h1>
        <div className="admin-header-actions">
          <button className="btn" onClick={() => { loadList(); }}>刷新列表</button>
          <button className="btn btn-logout" onClick={handleExit}>退出管理</button>
        </div>
      </header>

      {/* 生成邀请码 */}
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
          <button className="btn btn-primary" onClick={handleGenerate} disabled={generating}>
            {generating ? "生成中..." : "生成邀请码"}
          </button>
        </div>

        {/* 刚生成的码 */}
        {generatedCodes.length > 0 && (
          <div className="generated-codes">
            <h3>新生成的邀请码</h3>
            {generatedCodes.map((item) => (
              <div key={item.code} className="generated-code-item">
                <code className="code-value">{item.code}</code>
                <button className="btn btn-sm" onClick={() => handleCopy(item.code)}>复制</button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* 邀请码列表 */}
      <section className="admin-section">
        <h2>邀请码列表（{invites.length} 条）</h2>
        {loading ? (
          <p>加载中...</p>
        ) : invites.length === 0 ? (
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
                        <button className="btn btn-sm btn-error" onClick={() => handleRevoke(item.code)}>
                          作废
                        </button>
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
  );
}
