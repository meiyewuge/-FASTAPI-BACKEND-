import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  getProductionOrder, p2bThemeKernels, p2bExecutionPlansPreview,
  p2bExecutionPlansConfirm, p2bExplainExecutionPlan,
  p2bExecutionPlansByPO, p2bListSkills,
  clearAuth, isAdmin,
  type ProductionOrder as PO,
  type ThemeKernel as TK,
  type ExecutionPlan as EP,
  type ExecutionPlanPreviewResult as EPPreview,
  type ExecutionPlanConfirmResult as EPConfirm,
  type ExecutionPlanExplain as EPExplain,
  type P2BSkillItem,
  type ExecutionPlanSkillChainItem,
} from "../api/client";

// ---- 辅助 ----
function JsonBlock({ data, label }: { data: unknown; label?: string }) {
  const [open, setOpen] = useState(false);
  if (data == null) return null;
  return (
    <div className="p2b-json-block">
      <span className="p2b-json-toggle" onClick={() => setOpen(!open)}>
        {open ? "▼" : "▶"} {label || "详情"}
      </span>
      {open && <pre className="p2b-json-pre">{JSON.stringify(data, null, 2)}</pre>}
    </div>
  );
}

function CostBadge({ cost }: { cost: number | string | null | undefined }) {
  const val = cost == null ? 0 : typeof cost === "number" ? cost : parseFloat(String(cost)) || 0;
  return <span className={`p2b-cost-badge ${val === 0 ? "cost-zero" : "cost-paid"}`}>¥{val.toFixed(2)}</span>;
}

function parseVariantPlan(v?: string | Record<string, unknown> | null): Record<string, unknown> | null {
  if (!v) return null;
  if (typeof v === "object") return v;
  if (typeof v === "string") {
    try { return JSON.parse(v); } catch { return null; }
  }
  return null;
}

function getVariantPlan(p: EP): Record<string, unknown> | null {
  if (p.variant_plan && typeof p.variant_plan === "object") {
    return p.variant_plan as Record<string, unknown>;
  }
  return parseVariantPlan(p.variant_plan_json);
}

function renderPlanValue(v: unknown): React.ReactNode {
  if (v == null) return "暂无";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  return <pre className="p2b-json-pre">{JSON.stringify(v, null, 2)}</pre>;
}

function skillChainLabel(step: ExecutionPlanSkillChainItem | string): string {
  if (typeof step === "string") return step;
  return step.display_name || step.skill_id;
}

function skillChainId(step: ExecutionPlanSkillChainItem | string): string {
  return typeof step === "string" ? step : step.skill_id;
}

// ====================== 主组件 ======================
export default function P2BPreviewWorkbench() {
  const navigate = useNavigate();
  const [toast, setToast] = useState("");
  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 4000); };

  // ---- Step 1 ----
  const [productionOrderId, setProductionOrderId] = useState("");
  const [poData, setPoData] = useState<PO | null>(null);
  const [step1Loading, setStep1Loading] = useState(false);

  // ---- Step 2 ----
  const [themeKernel, setThemeKernel] = useState<TK | null>(null);
  const [kernelLocked, setKernelLocked] = useState(false);
  const [step2Loading, setStep2Loading] = useState(false);

  // ---- Step 3 ----
  const [previewData, setPreviewData] = useState<EPPreview | null>(null);
  const [expandedPlan, setExpandedPlan] = useState<string | null>(null);
  const [step3Loading, setStep3Loading] = useState(false);

  // ---- Step 4 ----
  const [confirmResult, setConfirmResult] = useState<EPConfirm | null>(null);
  const [step4Loading, setStep4Loading] = useState(false);

  // ---- Step 5 ----
  const [storedPlans, setStoredPlans] = useState<EP[]>([]);
  const [explainData, setExplainData] = useState<EPExplain | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [step5Loading, setStep5Loading] = useState(false);

  // ---- L2 Skills ----
  const [skills, setSkills] = useState<P2BSkillItem[]>([]);
  const [skillsOpen, setSkillsOpen] = useState(false);

  const loadSkills = useCallback(async () => {
    const r = await p2bListSkills();
    if (r.code === 0 && r.data) {
      setSkills(r.data.items || []);
    }
  }, []);

  useEffect(() => { loadSkills(); }, [loadSkills]);

  // ==================== Step 1: 读取生产单 ====================
  const handleReadPO = async () => {
    if (!productionOrderId.trim()) { showToast("请输入生产单 ID"); return; }
    setStep1Loading(true);
    setPoData(null); setThemeKernel(null); setKernelLocked(false);
    setPreviewData(null); setConfirmResult(null); setStoredPlans([]);
    const r = await getProductionOrder(productionOrderId.trim());
    setStep1Loading(false);
    if (r.code !== 0 || !r.data) {
      showToast(r.message || "未找到生产单，请先在 P2A 工作台创建生产单。");
      return;
    }
    setPoData(r.data);
    localStorage.setItem("p2b_last_po_id", r.data.production_order_id);
    showToast("生产单已读取");
  };

  // ==================== Step 2: 中心思想 ====================
  const handleThemeKernel = async () => {
    if (!poData) return;
    setStep2Loading(true);
    const r = await p2bThemeKernels(poData.production_order_id);
    setStep2Loading(false);
    if (r.code !== 0 || !r.data) { showToast(r.message || "中心思想生成失败"); return; }
    setThemeKernel(r.data);
    setKernelLocked(false);
    showToast("中心思想已生成");
  };

  // ==================== Step 3: 预览 30 条 ====================
  const handlePreview = async () => {
    if (!poData) return;
    setStep3Loading(true);
    setPreviewData(null);
    const r = await p2bExecutionPlansPreview(poData.production_order_id);
    setStep3Loading(false);
    if (r.code !== 0 || !r.data) { showToast(r.message || "执行计划预览失败"); return; }
    setPreviewData(r.data);
    showToast(`预览 ${(r.data.total_count ?? (r.data.plans?.length || 0))} 条执行计划`);
  };

  // ==================== Step 4: 确认入库 ====================
  const handleConfirm = async () => {
    if (!poData) return;
    setStep4Loading(true);
    const r = await p2bExecutionPlansConfirm(poData.production_order_id);
    setStep4Loading(false);
    if (r.code !== 0 || !r.data) { showToast(r.message || "确认入库失败"); return; }
    setConfirmResult(r.data);
    showToast(r.data.idempotent === true ? "已存在，未重复生成" : "已确认入库");
  };

  // ==================== Step 5: 查看已入库 ====================
  const handleLoadStored = async () => {
    if (!poData) return;
    setStep5Loading(true);
    const r = await p2bExecutionPlansByPO(poData.production_order_id);
    setStep5Loading(false);
    if (r.code !== 0 || !r.data) { showToast(r.message || "查询已入库计划失败"); return; }
    const plans = r.data.execution_plans || r.data.items || r.data.plans || [];
    setStoredPlans(plans);
    setExplainData(null);
    showToast(`已入库 ${plans.length} 条`);
  };

  const handleExplain = async (planId: string) => {
    setExplainLoading(true);
    setExplainData(null);
    const r = await p2bExplainExecutionPlan(planId);
    setExplainLoading(false);
    if (r.code !== 0 || !r.data) { showToast(r.message || "explain 查询失败"); return; }
    setExplainData(r.data);
  };

  // ==================== 获取全部 plans（兼容顶层和嵌套）====================
  const getAllPlans = (data: EPPreview): EP[] => {
    if (Array.isArray(data.execution_plans) && data.execution_plans.length > 0) return data.execution_plans;
    if (Array.isArray(data.plans) && data.plans.length > 0) return data.plans;
    if (Array.isArray(data.groups)) return data.groups.flatMap(g => g.plans || []);
    return [];
  };

  // ==================== Render ====================
  return (
    <div className="wf-root">
      {toast && <div className="toast-bar">{toast}</div>}

      {/* Header */}
      <header className="wf-header">
        <div className="wf-header-left">
          <h2>P2B-A 🎬 后期制作脑子预览</h2>
        </div>
        <div className="wf-header-right">
          <button className="btn btn-admin" onClick={() => navigate("/workbench")}>返回工作台</button>
          <button className="btn btn-admin" onClick={() => navigate("/p2a-preview")} style={{ background: "#6366f1", color: "#fff" }}>📋 P2A 预览</button>
          {isAdmin() && <button className="btn btn-admin" onClick={() => navigate("/admin")}>管理员</button>}
          <button className="btn-logout" onClick={() => { clearAuth(); navigate("/login", { replace: true }); }}>退出</button>
        </div>
      </header>

      {/* 黄色横幅 */}
      <div className="p2b-banner">P2B-A 预览模式 · 只出计划，不执行视频 · cost=¥0</div>

      {/* ===== Step 1: 选择生产单 ===== */}
      <section className="p2b-step">
        <h3>Step 1：选择生产单</h3>
        <div className="p2b-form-row">
          <label>production_order_id
            <input type="text" className="p2b-input" value={productionOrderId}
              onChange={e => setProductionOrderId(e.target.value)}
              placeholder="输入生产单 ID" />
          </label>
        </div>
        <div className="p2b-actions">
          <button className="btn p2b-btn-quick" onClick={() => {
            const last = localStorage.getItem("p2b_last_po_id");
            if (last) setProductionOrderId(last);
            else showToast("暂无最近测试生产单");
          }}>📋 使用最近测试生产单</button>
          <button className="btn p2b-btn-primary" onClick={handleReadPO}
            disabled={step1Loading || !productionOrderId.trim()}>
            {step1Loading ? "读取中…" : "读取生产单"}
          </button>
        </div>
        {poData && (
          <div className="p2b-po-card">
            <div className="p2b-po-row"><span>production_order_id</span><span className="p2b-mono">{poData.production_order_id}</span></div>
            <div className="p2b-po-row"><span>status</span><span className="p2b-status-tag">{poData.status}</span></div>
            <div className="p2b-po-row"><span>scenario</span><span>{poData.scenario || "-"}</span></div>
            <div className="p2b-po-row"><span>platform</span><span>{poData.platform || "-"}</span></div>
            <div className="p2b-po-row"><span>duration</span><span>{poData.duration}s</span></div>
          </div>
        )}
      </section>

      {/* ===== Step 2: 中心思想 ===== */}
      {poData && (
        <section className="p2b-step">
          <h3>Step 2：中心思想</h3>
          {!themeKernel && (
            <button className="btn p2b-btn-primary" onClick={handleThemeKernel} disabled={step2Loading}>
              {step2Loading ? "生成中…" : "生成中心思想"}
            </button>
          )}
          {themeKernel && (
            <div className={`p2b-kernel-card ${kernelLocked ? "locked" : ""}`}>
              <div className="p2b-kernel-row"><label>核心信息</label><div className="p2b-kernel-big">{themeKernel.core_message || "-"}</div></div>
              <div className="p2b-kernel-row"><label>情感钩子</label><div>{themeKernel.emotional_hook || "-"}</div></div>
              <div className="p2b-kernel-row"><label>核心承诺</label><div>{themeKernel.main_promise || "-"}</div></div>
              <div className="p2b-kernel-row"><label>行动号召</label><div>{themeKernel.cta_intent || "-"}</div></div>
              <div className="p2b-kernel-row"><label>必保要点</label>
                <div className="p2b-tag-list">{(themeKernel.must_keep_points || []).map((p, i) => <span key={i} className="p2b-tag">{p}</span>)}</div>
              </div>
              <div className="p2b-kernel-row"><label>禁改红线</label>
                <div className="p2b-tag-list">{(themeKernel.must_not_change || []).map((p, i) => <span key={i} className="p2b-tag p2b-tag-red">{p}</span>)}</div>
              </div>
              <div className="p2b-kernel-row"><label>品牌记忆点</label><div>{themeKernel.brand_memory_point || "-"}</div></div>
              {!kernelLocked && (
                <button className="btn p2b-btn-primary" onClick={() => { setKernelLocked(true); showToast("中心思想已锁定"); }}>
                  确认中心思想
                </button>
              )}
              {kernelLocked && <div className="p2b-locked-badge">✅ 已锁定</div>}
            </div>
          )}
        </section>
      )}

      {/* ===== Step 3: 预览 30 条 ===== */}
      {poData && kernelLocked && (
        <section className="p2b-step">
          <h3>Step 3：预览 30 条执行计划</h3>
          {!previewData && (
            <button className="btn p2b-btn-primary" onClick={handlePreview} disabled={step3Loading}>
              {step3Loading ? "生成中…" : "生成执行计划预览"}
            </button>
          )}
          {previewData && (() => {
            const allPlans = getAllPlans(previewData);
            const groupCount = previewData.groups?.length || new Set(allPlans.map(p => p.group_type)).size || 0;
            const dedupRate = previewData.dedup_report?.dedup_rate ?? previewData.dedup_rate ?? "100%";
            return (
              <div className="p2b-preview-section">
                <div className="p2b-summary">
                  <span>{allPlans.length} 条执行计划</span>
                  <span>{groupCount} 组策略</span>
                  <span>去重率 {String(dedupRate)}</span>
                  <span><CostBadge cost={previewData.cost_estimate ?? 0} /></span>
                  <span className="p2b-allowed-tag">{previewData.execute_allowed === true ? "⚠️ 允许执行" : "🔒 不执行视频"}</span>
                </div>
                <div className="p2b-plan-grid">
                  {allPlans.map((p, i) => {
                    const key = p.variant_id || p.execution_plan_id || `plan-${i}`;
                    const isExpanded = expandedPlan === key;
                    return (
                      <div key={key} className={`p2b-plan-card ${isExpanded ? "expanded" : ""}`}
                        onClick={() => setExpandedPlan(isExpanded ? null : key)}>
                        <div className="p2b-card-header">
                          <span className="p2b-card-idx">#{i + 1}</span>
                          <span className="p2b-card-group">{p.group_type_cn || p.group_type || "-"}</span>
                        </div>
                        <div className="p2b-card-id p2b-mono">{p.variant_id || p.execution_plan_id || "-"}</div>
                        <div className="p2b-card-field"><span>高光</span><span>{p.highlight_focus_cn || "-"}</span></div>
                        <div className="p2b-card-field"><span>视觉</span><span>{p.visual_style_cn || "-"}</span></div>
                        <div className="p2b-card-skills">
                          {(p.skill_chain || []).slice(0, 4).map((s, si) => (
                            <span key={si} className="p2b-skill-tag">{skillChainLabel(s)}</span>
                          ))}
                        </div>
                        <div className="p2b-card-footer">
                          <CostBadge cost={p.cost_estimate ?? 0} />
                          <span className="p2b-allowed-mini">{p.execute_allowed === true ? "⚠️" : "🔒"}</span>
                        </div>

                        {/* 展开详情 */}
                        {isExpanded && (() => {
                          const vp = getVariantPlan(p);
                          const craft = p.craft_explanation || vp?.craft_explanation;
                          const rhythm = p.rhythm_plan || vp?.rhythm_plan;
                          const transition = p.transition_plan || vp?.transition_plan;
                          const subtitle = p.subtitle_plan || vp?.subtitle_plan;
                          const highlight = p.highlight_card_plan || vp?.highlight_card_plan;
                          const uniqueness = p.uniqueness_plan || vp?.uniqueness_plan;
                          const cta = p.cta_plan || vp?.cta_plan;
                          return (
                          <div className="p2b-card-detail" onClick={e => e.stopPropagation()}>
                            {craft != null && <div className="p2b-detail-block"><h5>craft_explanation</h5><div>{renderPlanValue(craft)}</div></div>}
                            {rhythm != null && <div className="p2b-detail-block"><h5>rhythm_plan</h5><div>{renderPlanValue(rhythm)}</div></div>}
                            {transition != null && <div className="p2b-detail-block"><h5>transition_plan</h5><div>{renderPlanValue(transition)}</div></div>}
                            {subtitle != null && <div className="p2b-detail-block"><h5>subtitle_plan</h5><div>{renderPlanValue(subtitle)}</div></div>}
                            {highlight != null && <div className="p2b-detail-block"><h5>highlight_card_plan</h5><div>{renderPlanValue(highlight)}</div></div>}
                            {uniqueness != null && <div className="p2b-detail-block"><h5>uniqueness_plan</h5><div>{renderPlanValue(uniqueness)}</div></div>}
                            {cta != null && <div className="p2b-detail-block"><h5>cta_plan</h5><div>{renderPlanValue(cta)}</div></div>}
                            {p.skill_chain && (
                              <div className="p2b-detail-block">
                                <h5>skill_chain</h5>
                                <div className="p2b-skill-chain-full">
                                  {p.skill_chain.map((s, si) => (
                                    <span key={si} className="p2b-skill-step">
                                      <span className="p2b-skill-num">{si + 1}</span>
                                      <span className="p2b-skill-name">{skillChainLabel(s)}</span>
                                      <span className="p2b-skill-id">{skillChainId(s)}</span>
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}
                            {vp && (
                              <JsonBlock data={vp} label="variant_plan" />
                            )}
                          </div>
                          );
                        })()}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })()}
        </section>
      )}

      {/* ===== Step 4: 确认入库 ===== */}
      {previewData && !confirmResult && (
        <section className="p2b-step">
          <h3>Step 4：确认入库</h3>
          <button className="btn p2b-btn-primary" onClick={handleConfirm} disabled={step4Loading}>
            {step4Loading ? "确认中…" : "确认入库 30 条"}
          </button>
        </section>
      )}
      {confirmResult && (
        <section className="p2b-step">
          <h3>Step 4：确认入库 ✅</h3>
          <div className="p2b-confirm-card">
            <div className="p2b-confirm-row"><span>状态</span><span className="p2b-status-tag">{confirmResult.status || "confirmed"}</span></div>
            <div className="p2b-confirm-row"><span>已确认条数</span><strong>{confirmResult.confirmed_count ?? 30}</strong></div>
            <div className="p2b-confirm-row"><span>cost</span><CostBadge cost={confirmResult.cost_estimate ?? 0} /></div>
            <div className="p2b-confirm-row"><span>execute_allowed</span>
              <span className="p2b-allowed-tag">{confirmResult.execute_allowed === true ? "⚠️ 允许" : "🔒 不执行视频"}</span>
            </div>
            <div className="p2b-confirm-row"><span>幂等</span>
              <span>{confirmResult.idempotent === true ? "已存在，未重复生成" : "已确认入库"}</span>
            </div>
          </div>
        </section>
      )}

      {/* ===== Step 5: 查看已入库 ===== */}
      {confirmResult && (
        <section className="p2b-step">
          <h3>Step 5：查看已入库计划</h3>
          {storedPlans.length === 0 && (
            <button className="btn p2b-btn-primary" onClick={handleLoadStored} disabled={step5Loading}>
              {step5Loading ? "加载中…" : "查看已入库计划"}
            </button>
          )}
          {storedPlans.length > 0 && (
            <div>
              <h4>{storedPlans.length} 条已入库计划</h4>
              <div className="p2b-stored-list">
                {storedPlans.map((p, i) => {
                  const planId = p.execution_plan_id || p.variant_id || `stored-${i}`;
                  return (
                    <div key={planId} className="p2b-stored-item"
                      onClick={() => handleExplain(planId)}>
                      <span className="p2b-stored-idx">#{i + 1}</span>
                      <span className="p2b-mono">{planId}</span>
                      <span>{p.group_type_cn || p.group_type || "-"}</span>
                      <span>{p.highlight_focus_cn || "-"}</span>
                      <span className="p2b-stored-status">{p.status || "confirmed"}</span>
                    </div>
                  );
                })}
              </div>
              {explainLoading && <div className="p2b-loading">加载 explain 中…</div>}
              {explainData && (
                <div className="p2b-explain-card">
                  <h4>Explain: {explainData.execution_plan_id || explainData.variant_id || "-"}</h4>
                  {explainData.theme_core_message && <div className="p2b-explain-row"><label>核心信息</label><p>{explainData.theme_core_message}</p></div>}
                  {explainData.rhythm_explanation && <div className="p2b-explain-row"><label>节奏说明</label><p>{explainData.rhythm_explanation}</p></div>}
                  {explainData.transition_explanation && <div className="p2b-explain-row"><label>转场说明</label><p>{explainData.transition_explanation}</p></div>}
                  {explainData.subtitle_explanation && <div className="p2b-explain-row"><label>字幕说明</label><p>{explainData.subtitle_explanation}</p></div>}
                  {explainData.highlight_card_explanation && <div className="p2b-explain-row"><label>高光卡说明</label><p>{explainData.highlight_card_explanation}</p></div>}
                  {explainData.uniqueness_explanation && <div className="p2b-explain-row"><label>去重说明</label><p>{explainData.uniqueness_explanation}</p></div>}
                  {explainData.craft_explanation && <div className="p2b-explain-row"><label>工艺说明</label><p>{explainData.craft_explanation}</p></div>}
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {/* ===== L2 技能面板 ===== */}
      <section className="p2b-skills-panel">
        <h4 onClick={() => setSkillsOpen(!skillsOpen)} style={{ cursor: "pointer" }}>
          {skillsOpen ? "▼" : "▶"} P2B L2 技能库（只读，{skills.length} 条）
        </h4>
        {skillsOpen && (
          <div className="p2b-skills-grid">
            {skills.map(s => (
              <div key={s.skill_id} className="p2b-skill-card">
                <div className="p2b-skill-name-lg">{s.display_name || s.name}</div>
                <div className="p2b-skill-meta">{s.category} · {s.layer}</div>
                <div className="p2b-skill-desc">{s.description || "-"}</div>
                <div className="p2b-skill-id">{s.skill_id}</div>
              </div>
            ))}
            {skills.length === 0 && <div className="p2b-loading">暂无技能数据</div>}
          </div>
        )}
      </section>
    </div>
  );
}
