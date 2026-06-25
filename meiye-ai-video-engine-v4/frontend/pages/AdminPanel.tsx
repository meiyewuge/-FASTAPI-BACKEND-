/**
 * 管理员后台 — JWT role 模式（Patch6 已上线）
 * super_admin: 完整管理（发码 + 用户授权）
 * invite_admin: 仅发码管理
 * user: 无权限，跳工作台
 */
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  adminInviteGenerate, adminInviteList, adminInviteRevoke,
  adminGrantUser, adminRevokeUser, adminListUsers,
  getToken, getUserProfile, fetchMe,
  isAdmin, isSuperAdmin, getCurrentUserRole,
  type InviteItem, type AdminUserItem, type UserRole,
} from "../api/client";

export default function AdminPanel() {
  const navigate = useNavigate();
  const [profileLoaded, setProfileLoaded] = useState(false);

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

  // 用户授权管理（super_admin only）
  const [adminUsers, setAdminUsers] = useState<AdminUserItem[]>([]);
  const [grantPhone, setGrantPhone] = useState("");
  const [grantRole, setGrantRole] = useState<UserRole>("invite_admin");
  const [granting, setGranting] = useState(false);
  const [activeTab, setActiveTab] = useState<"invite" | "users">("invite");

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 3000); };

  // 未登录跳回；确保 profile 已加载
  useEffect(() => {
    if (!getToken()) { navigate("/login", { replace: true }); return; }
    const loadProfile = async () => {
      if (!getUserProfile()) await fetchMe();
      setProfileLoaded(true);
      // 非管理员跳工作台
      if (!isAdmin()) navigate("/workbench", { replace: true });
    };
    loadProfile();
  }, [navigate]);

  // 加载邀请码列表
  const loadList = useCallback(async () => {
    setLoading(true);
    const r = await adminInviteList();
    if (r.code === 0 && r.data) setInvites(r.data.items || []);
    else showToast(r.message || "加载失败");
    setLoading(false);
  }, []);

  // 加载管理员列表（super_admin）
  const loadAdminUsers = useCallback(async () => {
    if (!isSuperAdmin()) return;
    const r = await adminListUsers();
    if (r.code === 0 && r.data) setAdminUsers(r.data.items || []);
  }, []);

  useEffect(() => {
    if (profileLoaded && isAdmin()) {
      loadList();
      if (isSuperAdmin()) loadAdminUsers();
    }
  }, [profileLoaded, loadList, loadAdminUsers]);

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
    if (r.code === 0) { showToast(`邀请码 ${code} 已作废`); loadList(); }
    else showToast(r.message || "作废失败");
  };

  // 复制
  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text).then(
      () => showToast(`已复制: ${text}`),
      () => showToast("复制失败，请手动复制"),
    );
  };

  // 授权员工
  const handleGrant = async () => {
    if (!grantPhone.trim()) { showToast("请输入手机号"); return; }
    setGranting(true);
    const r = await adminGrantUser(grantPhone.trim(), grantRole);
    if (r.code === 0) {
      showToast(`${grantPhone} 已授权为 ${grantRole}`);
      setGrantPhone("");
      loadAdminUsers();
    } else {
      showToast(r.message || "授权失败");
    }
    setGranting(false);
  };

  // 取消授权
  const handleRevokeUser = async (phone: string) => {
    if (!confirm(`确定取消 ${phone} 的管理员权限？`)) return;
    const r = await adminRevokeUser(phone);
    if (r.code === 0) { showToast(`${phone} 管理员权限已取消`); loadAdminUsers(); }
    else showToast(r.message || "取消失败");
  };

  // 退出
  const handleExit = () => navigate("/workbench", { replace: true });

  // 等待 profile 加载
  if (!profileLoaded) return <div className="admin-page"><p style={{ padding: 40 }}>加载中...</p></div>;

  const role = getCurrentUserRole();
  const isSuper = role === "super_admin";

  return (
    <div className="admin-page">
      {toast && <div className="toast">{toast}</div>}

      <header className="admin-header">
        <h1>管理员后台
          <span className="role-badge">{isSuper ? "超级管理员" : "发码管理员"}</span>
        </h1>
        <div className="admin-header-actions">
          <button className="btn" onClick={() => { loadList(); if (isSuper) loadAdminUsers(); }}>刷新</button>
          <button className="btn btn-logout" onClick={handleExit}>返回工作台</button>
        </div>
      </header>

      {/* Tab 切换 */}
      {isSuper && (
        <div className="admin-tabs">
          <button className={activeTab === "invite" ? "tab active" : "tab"}
            onClick={() => setActiveTab("invite")}>邀请码管理</button>
          <button className={activeTab === "users" ? "tab active" : "tab"}
            onClick={() => setActiveTab("users")}>用户授权</button>
        </div>
      )}

      {/* ======== 邀请码管理（super_admin + invite_admin 均可见）======== */}
      {(activeTab === "invite" || !isSuper) && (
        <>
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

          <section className="admin-section">
            <h2>邀请码列表（{invites.length} 条）</h2>
            {loading ? <p>加载中...</p> : invites.length === 0 ? (
              <p className="empty-state">暂无邀请码</p>
            ) : (
              <div className="admin-table-wrap">
                <table className="task-table admin-table">
                  <thead><tr><th>邀请码</th><th>备注</th><th>绑定手机号</th><th>已用/上限</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead>
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
                        <td><span className={`tag ${item.active ? "tag-done" : "tag-failed"}`}>{item.active ? "有效" : "已作废"}</span></td>
                        <td>{item.created_at ? new Date(item.created_at).toLocaleString("zh-CN") : "-"}</td>
                        <td>{item.active && <button className="btn btn-sm btn-error" onClick={() => handleRevoke(item.code)}>作废</button>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}

      {/* ======== 用户授权管理（仅 super_admin）======== */}
      {isSuper && activeTab === "users" && (
        <section className="admin-section">
          <h2>用户授权管理</h2>
          <div className="admin-form" style={{ marginBottom: 16 }}>
            <div className="admin-form-row">
              <label>手机号</label>
              <input type="tel" placeholder="员工手机号" value={grantPhone}
                onChange={(e) => setGrantPhone(e.target.value)} />
            </div>
            <div className="admin-form-row">
              <label>角色</label>
              <select value={grantRole} onChange={(e) => setGrantRole(e.target.value as UserRole)}
                style={{ padding: "7px 10px", border: "1px solid var(--border)", borderRadius: "var(--radius)" }}>
                <option value="invite_admin">发码管理员</option>
              </select>
            </div>
            <button className="btn btn-primary" onClick={handleGrant} disabled={granting}>
              {granting ? "授权中..." : "授权"}
            </button>
          </div>

          {adminUsers.length === 0 ? (
            <p className="empty-state">暂无授权用户</p>
          ) : (
            <div className="admin-table-wrap">
              <table className="task-table admin-table">
                <thead><tr><th>手机号</th><th>角色</th><th>操作</th></tr></thead>
                <tbody>
                  {adminUsers.map((u) => (
                    <tr key={u.phone}>
                      <td>{u.phone}</td>
                      <td><span className="tag tag-done">{u.role}</span></td>
                      <td>
                        {u.role !== "super_admin" && (
                          <button className="btn btn-sm btn-error" onClick={() => handleRevokeUser(u.phone)}>取消授权</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
