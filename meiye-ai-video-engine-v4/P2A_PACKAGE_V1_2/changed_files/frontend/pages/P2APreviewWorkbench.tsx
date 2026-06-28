/**
 * P2A Preview Workbench — 最小预览工作台（Preview Only，不执行裂变）
 *
 * 4 步线性流程：
 *   Step 1：选择导演稿 → API 1 POST /production-orders/preview
 *   Step 2：展示生产单 Preview + shot_maps → API 2 POST /production-orders
 *   Step 3：确认创建 → API 3 GET /production-orders/{id}（二次确认）
 *   Step 4：裂变计划 Preview → API 4 POST /fission-plans/preview
 *
 * 技能库：API 5 GET /skills（只读）
 *
 * 禁止：无 execute 按钮 / 不调 remixer / 不触发火山 / 不写 videos / 不进 production
 */
import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  productionOrderPreview, createProductionOrder, getProductionOrder,
  fissionPlanPreview, listSkills,
  getToken, clearAuth, isAdmin,
  type ProductionOrderPreview as POPreview,
  type ProductionOrder as PO,
  type FissionPlanPreview as FPPreview,
  type Variant, type ShotMap, type SkillItem, type SegmentPlan,
  type SkillSequenceItem,
} from "../api/client";

// ---- 测试导演稿 ID ----
const TEST_DIRECTOR_PLAN_ID = "76f9b973f3354165a6ddaca993388533";

// ---- Group 中文标签 ----
const GROUP_LABELS: Record<string, string> = {
  pain_first: "痛点优先",
  selling_first: "卖点优先",
  result_close: "效果收尾",
  brand_double: "品牌双打",
  same_source: "同源裂变",
  reverse: "反转策略",
};

// ---- 辅助 ----
function JsonBlock({ data, label }: { data: unknown; label?: string }) {
  const [open, setOpen] = useState(false);
  if (data == null) return null;
  return (
    <div className="p2a-json-block">
      <span className="p2a-json-toggle" onClick={() => setOpen(!open)}>
        {open ? "▼" : "▶"} {label || "详情"}
      </span>
      {open && <pre className="p2a-json-pre">{JSON.stringify(data, null, 2)}</pre>}
    </div>
  );
}

function CostBadge({ cost }: { cost: number | string }) {
  const val = typeof cost === "number" ? cost : parseFloat(String(cost)) || 0;
  return (
    <span className={`p2a-cost-badge ${val === 0 ? "cost-zero" : "cost-paid"}`}>
      ¥{val.toFixed(2)}
    </span>
  );
}

// ====================== 主组件 ======================
export default function P2APreviewWorkbench() {
  const navigate = useNavigate();
  const [toast, setToast] = useState("");

  // ---- Step 1 状态 ----
  const [directorPlanId, setDirectorPlanId] = useState("");
  const [scenario, setScenario] = useState("product_seeding");
  const [platform, setPlatform] = useState("douyin");
  const [step1Loading, setStep1Loading] = useState(false);

  // ---- Step 2 状态 ----
  const [poPreview, setPoPreview] = useState<POPreview | null>(null);
  const [step2Loading, setStep2Loading] = useState(false);

  // ---- Step 3 状态 ----
  const [confirmedPO, setConfirmedPO] = useState<PO | null>(null);
  const [step3Loading, setStep3Loading] = useState(false);

  // ---- Step 4 状态 ----
  const [fissionPlan, setFissionPlan] = useState<FPPreview | null>(null);
  const [step4Loading, setStep4Loading] = useState(false);
  const [expandedVariant, setExpandedVariant] = useState<string | null>(null);

  // ---- Skills ----
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [skillsPanelOpen, setSkillsPanelOpen] = useState(false);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(""), 4000); };

  // ---- Skill 名称映射 ----
  const skillMap = useCallback(() => {
    const m: Record<string, string> = {};
    skills.forEach(s => { m[s.skill_id] = s.name; });
    return m;
  }, [skills])();

  // ---- 加载 Skills ----
  const loadSkills = async () => {
    setSkillsLoading(true);
    const r = await listSkills();
    if (r.code === 0 && r.data) {
      setSkills(r.data.items || []);
    } else {
      showToast(r.message || "技能列表加载失败");
    }
    setSkillsLoading(false);
  };

  useEffect(() => { loadSkills(); }, []);

  // ==================== Step 1：生产单 Preview ====================
  const handleStep1 = async () => {
    if (!directorPlanId.trim()) { showToast("请输入导演稿 ID"); return; }
    setStep1Loading(true);
    setPoPreview(null); setConfirmedPO(null); setFissionPlan(null);

    const r = await productionOrderPreview(directorPlanId.trim(), scenario, platform);
    setStep1Loading(false);
    if (r.code !== 0 || !r.data) {
      showToast(r.message || "生产单预览请求失败");
      return;
    }
    setPoPreview(r.data);
    showToast("生产单 Preview 已生成");
  };

  // ==================== Step 2：确认创建生产单 ====================
  const handleStep2 = async () => {
    if (!poPreview) return;
    setStep2Loading(true);

    // API 2: 创建生产单
    const r2 = await createProductionOrder(
      poPreview.director_plan_id, poPreview.scenario || "product_seeding", poPreview.platform || "douyin",
    );
    if (r2.code !== 0 || !r2.data) {
      setStep2Loading(false);
      showToast(r2.message || "创建生产单失败");
      return;
    }
    const poId = r2.data.production_order_id;

    // API 3: 二次确认 — 查询正式生产单
    const r3 = await getProductionOrder(poId);
    setStep2Loading(false);
    if (r3.code !== 0 || !r3.data) {
      showToast(r3.message || "查询正式生产单失败，请检查 tenant 隔离");
      return;
    }
    setConfirmedPO(r3.data);
    showToast(`生产单已确认：${poId}`);
  };

  // ==================== Step 3：裂变计划 Preview ====================
  const handleStep3 = async () => {
    if (!confirmedPO) return;
    setStep4Loading(true);
    setFissionPlan(null);

    const r = await fissionPlanPreview(confirmedPO.production_order_id);
    setStep4Loading(false);
    if (r.code !== 0 || !r.data) {
      showToast(r.message || "裂变计划预览失败");
      return;
    }
    setFissionPlan(r.data);
    showToast(`裂变计划 Preview：${r.data.target_count} 条 variant`);
  };

  // ==================== Render Helpers ====================
  const renderShotMaps = (shots: ShotMap[]) => (
    <div className="p2a-table-wrap">
      <table className="p2a-table">
        <thead>
          <tr>
            <th>shot_id</th><th>role</th><th>start</th><th>end</th>
            <th>text_content</th><th>visual_description</th><th>confidence</th>
          </tr>
        </thead>
        <tbody>
          {shots.map((s, i) => (
            <tr key={s.shot_id || i}>
              <td className="p2a-mono">{s.shot_id}</td>
              <td><span className={`p2a-role-tag role-${s.role?.toLowerCase().replace(/\s+/g, "-")}`}>{s.role}</span></td>
              <td>{s.start_time}</td>
              <td>{s.end_time}</td>
              <td className="p2a-cell-text">{s.text_content}</td>
              <td className="p2a-cell-text">{s.visual_description}</td>
              <td>{typeof s.confidence === "number" ? `${(s.confidence * 100).toFixed(0)}%` : s.confidence}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  const renderVariantDetail = (v: Variant) => (
    <div className="p2a-variant-detail">
      {/* segment_plan */}
      <div className="p2a-detail-section">
        <h5>segment_plan ({v.segment_plan?.length || 0})</h5>
        <JsonBlock data={v.segment_plan} label="segment_plan JSON" />
      </div>

      {/* skill_sequence 横向步骤条 */}
      <div className="p2a-detail-section">
        <h5>skill_sequence ({v.skill_sequence?.length || 0})</h5>
        <div className="p2a-skill-steps">
          {v.skill_sequence?.map((step, i) => {
            const skillId = typeof step === "string" ? step : step?.skill_id;
            return (
              <div key={i} className="p2a-skill-step">
                <span className="p2a-skill-num">{i + 1}</span>
                <span className="p2a-skill-name">{skillMap[skillId] || skillId}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* output_requirements */}
      {v.output_requirements && (
        <div className="p2a-detail-section">
          <h5>output_requirements</h5>
          <JsonBlock data={v.output_requirements} label="output_requirements" />
        </div>
      )}

      {/* qa_expected */}
      {v.qa_expected && (
        <div className="p2a-detail-section">
          <h5>qa_expected</h5>
          <JsonBlock data={v.qa_expected} label="qa_expected" />
        </div>
      )}
    </div>
  );

  const renderFissionPlan = (fp: FPPreview) => {
    const allVariants =
      Array.isArray(fp.variants) && fp.variants.length > 0
        ? fp.variants
        : fp.groups?.flatMap(g => g.variants || []) || [];
    return (
      <div className="p2a-fission-plan">
        {/* 概要 */}
        <div className="p2a-fp-summary">
          <div className="p2a-fp-row"><span>fission_plan_id</span><span className="p2a-mono">{fp.fission_plan_id}</span></div>
          <div className="p2a-fp-row"><span>production_order_id</span><span className="p2a-mono">{fp.production_order_id}</span></div>
          <div className="p2a-fp-row"><span>tenant_id</span><span className="p2a-mono">{fp.tenant_id}</span></div>
          <div className="p2a-fp-row"><span>target_count</span><strong>{fp.target_count}</strong></div>
          <div className="p2a-fp-row"><span>status</span><span className="p2a-status-tag">{fp.status}</span></div>
          <div className="p2a-fp-row"><span>cost</span><CostBadge cost={0} /></div>
          <JsonBlock data={fp.qa_gates} label="qa_gates" />
          <div className="p2a-fp-row"><span>required_skills</span><span>{fp.required_skills?.join(", ") || "-"}</span></div>
        </div>

        {/* 6 组策略概览 */}
        <h4>6 组策略概览</h4>
        <div className="p2a-group-cards">
          {fp.groups?.map(g => (
            <div key={g.group_type} className="p2a-group-card">
              <div className="p2a-group-type">{GROUP_LABELS[g.group_type] || g.group_type}</div>
              <div className="p2a-group-count">{g.count} 条</div>
              <div className="p2a-group-key">{g.group_type}</div>
            </div>
          ))}
        </div>

        {/* 30 条 variant 表格 */}
        <h4>{allVariants.length} 条 Variant</h4>
        <div className="p2a-table-wrap">
          <table className="p2a-table p2a-variant-table">
            <thead>
              <tr>
                <th></th>
                <th>variant_id</th><th>group_type</th><th>center_idea</th>
                <th>segment</th><th>skills</th><th>seconds</th>
                <th>cost</th><th>qa_status</th>
              </tr>
            </thead>
            <tbody>
              {allVariants.map((v, i) => (
                <>
                  <tr key={v.variant_id} className={expandedVariant === v.variant_id ? "expanded" : ""}
                    onClick={() => setExpandedVariant(expandedVariant === v.variant_id ? null : v.variant_id)}>
                    <td className="p2a-expand-icon">{expandedVariant === v.variant_id ? "▼" : "▶"}</td>
                    <td className="p2a-mono">{v.variant_id}</td>
                    <td><span className="p2a-group-tag">{GROUP_LABELS[v.group_type] || v.group_type}</span></td>
                    <td className="p2a-cell-text">{v.center_idea}</td>
                    <td>{v.segment_plan?.length || 0}</td>
                    <td>{v.skill_sequence?.length || 0}</td>
                    <td>{String(v.output_requirements?.target_seconds ?? v.target_seconds ?? "-")}</td>
                    <td><CostBadge cost={(v.output_requirements?.cost as number | string) ?? v.cost ?? 0} /></td>
                    <td><span className={`p2a-qa-tag qa-${v.qa_status}`}>{v.qa_status}</span></td>
                  </tr>
                  {expandedVariant === v.variant_id && (
                    <tr key={`${v.variant_id}-detail`} className="p2a-variant-detail-row">
                      <td colSpan={9}>{renderVariantDetail(v)}</td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  // ==================== Skills 面板 ====================
  const renderSkillsPanel = () => (
    <div className="p2a-skills-panel">
      <h4 onClick={() => setSkillsPanelOpen(!skillsPanelOpen)} style={{ cursor: "pointer" }}>
        {skillsPanelOpen ? "▼" : "▶"} 技能库（只读，{skills.length} 条）
      </h4>
      {skillsPanelOpen && (
        <div className="p2a-table-wrap">
          {skillsLoading ? <div className="p2a-loading">加载中…</div> : (
            <table className="p2a-table">
              <thead>
                <tr>
                  <th>skill_id</th><th>name</th><th>category</th>
                  <th>engine</th><th>adapter</th><th>risk_level</th><th>enabled</th>
                </tr>
              </thead>
              <tbody>
                {skills.map(s => (
                  <tr key={s.skill_id}>
                    <td className="p2a-mono">{s.skill_id}</td>
                    <td>{s.name}</td>
                    <td>{s.category}</td>
                    <td>{s.engine}</td>
                    <td>{s.adapter}</td>
                    <td><span className={`p2a-risk-tag risk-${s.risk_level}`}>{s.risk_level}</span></td>
                    <td>{s.enabled ? "✅" : "❌"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );

  // ====================== RENDER ======================
  return (
    <div className="p2a-page">
      {toast && <div className="toast">{toast}</div>}

      {/* 黄色 Preview Only 横幅 */}
      <div className="p2a-preview-banner">
        ⚠️ Preview Only — 当前为预览模式，不执行真实裂变。cost = ¥0，不触发火山引擎。
      </div>

      {/* Header */}
      <header className="wf-header">
        <div className="wf-header-left">
          <h1>P2A 📋 预览工作台</h1>
          <span className="p2a-subtitle">生产单 → 裂变计划 · Preview Only</span>
        </div>
        <div className="wf-header-right">
          <button className="btn btn-admin" onClick={() => navigate("/workbench")}>返回工作台</button>
          {isAdmin() && (
            <button className="btn btn-admin" onClick={() => navigate("/admin")}>管理员</button>
          )}
          <button className="btn-logout" onClick={() => { clearAuth(); navigate("/login", { replace: true }); }}>退出</button>
        </div>
      </header>

      {/* ===== Step 1：选择导演稿 ===== */}
      <section className="p2a-step">
        <h3>Step 1：选择导演稿</h3>
        <div className="p2a-form-row">
          <label>director_plan_id
            <input type="text" className="p2a-input" value={directorPlanId}
              onChange={e => setDirectorPlanId(e.target.value)}
              placeholder="输入导演稿 ID" />
          </label>
          <label>scenario
            <select className="p2a-select" value={scenario} onChange={e => setScenario(e.target.value)}>
              <option value="product_seeding">产品种草</option>
              <option value="brand_story">品牌故事</option>
              <option value="tutorial">教程</option>
              <option value="comparison">对比评测</option>
              <option value="review">体验测评</option>
              <option value="event">活动宣传</option>
              <option value="testimony">用户证言</option>
            </select>
          </label>
          <label>platform
            <select className="p2a-select" value={platform} onChange={e => setPlatform(e.target.value)}>
              <option value="douyin">抖音</option>
              <option value="xiaohongshu">小红书</option>
              <option value="kuaishou">快手</option>
              <option value="shipinhao">微信视频号</option>
            </select>
          </label>
        </div>
        <div className="p2a-actions">
          <button className="btn p2a-btn-quick" onClick={() => setDirectorPlanId(TEST_DIRECTOR_PLAN_ID)}>
            📋 使用测试导演稿
          </button>
          <button className="btn p2a-btn-primary" onClick={handleStep1}
            disabled={step1Loading || !directorPlanId.trim()}>
            {step1Loading ? "加载中…" : "生成生产单 Preview"}
          </button>
        </div>
      </section>

      {/* ===== Step 2：生产单 Preview ===== */}
      {poPreview && (
        <section className="p2a-step">
          <h3>Step 2：生产单 Preview</h3>
          <div className="p2a-po-card">
            <div className="p2a-po-row"><span>production_order_id</span><span className="p2a-mono">{poPreview.production_order_id || "(preview)"}</span></div>
            <div className="p2a-po-row"><span>status</span><span className="p2a-status-tag">{poPreview.status}</span></div>
            <div className="p2a-po-row"><span>director_plan_id</span><span className="p2a-mono">{poPreview.director_plan_id}</span></div>
            <div className="p2a-po-row"><span>tenant_id</span><span className="p2a-mono">{poPreview.tenant_id}</span></div>
            <div className="p2a-po-row"><span>scenario / platform</span><span>{poPreview.scenario || "-"} / {poPreview.platform || "-"}</span></div>
            <div className="p2a-po-row"><span>ratio / duration</span><span>{poPreview.ratio} · {poPreview.duration}s</span></div>
            <div className="p2a-po-row"><span>fission_goal</span><span>{typeof poPreview.fission_goal === "object" ? JSON.stringify(poPreview.fission_goal) : poPreview.fission_goal}</span></div>
            <div className="p2a-po-row"><span>cost</span><CostBadge cost={0} /></div>
            <JsonBlock data={poPreview.qa_gates} label="qa_gates" />
            <JsonBlock data={poPreview.asset_policy} label="asset_policy" />
          </div>

          {/* shot_maps */}
          {poPreview.shot_maps?.length > 0 && (
            <div className="p2a-shotmaps">
              <h4>shot_maps ({poPreview.shot_maps.length})</h4>
              {renderShotMaps(poPreview.shot_maps)}
            </div>
          )}

          <div className="p2a-actions">
            <button className="btn p2a-btn-primary" onClick={handleStep2}
              disabled={step2Loading}>
              {step2Loading ? "创建中…" : "确认创建生产单"}
            </button>
          </div>
        </section>
      )}

      {/* ===== Step 3：生产单已确认 ===== */}
      {confirmedPO && (
        <section className="p2a-step">
          <h3>Step 3：生产单已确认 ✅</h3>
          <div className="p2a-po-card p2a-po-confirmed">
            <div className="p2a-po-row"><span>production_order_id</span><span className="p2a-mono">{confirmedPO.production_order_id}</span></div>
            <div className="p2a-po-row"><span>status</span><span className="p2a-status-tag p2a-status-confirmed">{confirmedPO.status}</span></div>
            <div className="p2a-po-row"><span>来源</span><span>API 3 二次确认（GET /production-orders/{confirmedPO.production_order_id}）</span></div>
          </div>

          {confirmedPO.shot_maps?.length > 0 && (
            <div className="p2a-shotmaps">
              <h4>正式 shot_maps ({confirmedPO.shot_maps.length})</h4>
              {renderShotMaps(confirmedPO.shot_maps)}
            </div>
          )}

          <div className="p2a-actions">
            <button className="btn p2a-btn-primary" onClick={handleStep3}
              disabled={step4Loading}>
              {step4Loading ? "生成中…" : "生成裂变计划 Preview"}
            </button>
          </div>
        </section>
      )}

      {/* ===== Step 4：裂变计划 Preview ===== */}
      {fissionPlan && (
        <section className="p2a-step">
          <h3>Step 4：裂变计划 Preview</h3>
          {renderFissionPlan(fissionPlan)}
        </section>
      )}

      {/* ===== 技能库（只读） ===== */}
      {renderSkillsPanel()}

      {/* 底部说明 */}
      <div className="p2a-footer-note">
        当前为 Preview Only，不执行真实裂变。所有 cost 均为 ¥0。
      </div>
    </div>
  );
}
