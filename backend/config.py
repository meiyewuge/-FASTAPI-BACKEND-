"""全局配置（pydantic-settings）。从环境变量 / .env 读取。"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    app_port: int = 8000

    # 数据库：默认 SQLite，零依赖即可运行；生产可换 PostgreSQL
    database_url: str = "sqlite:///./meiye_v4.db"

    # 多租户：未带租户信息时的默认 tenant
    default_tenant: str = "default"

    # 鉴权（Patch4：邀约码 + JWT）
    jwt_secret: str = "change_me"
    jwt_ttl_seconds: int = 7 * 24 * 3600   # token 有效期（默认 7 天）
    admin_key: str = ""                     # 管理员端点口令（X-Admin-Key）；空=禁用管理端点
    auth_required: bool = True              # 业务 API 是否强制 JWT（测试可关）

    # 视频生成 provider：mock | volcano_seedance | (future) keling / jimeng / runway ...
    video_provider: str = "mock"
    # 真实 provider 失败时是否兜底回退（最终回退到 mock，保证不中断）
    video_fallback: bool = True
    provider_retries: int = 3           # 真实 provider 失败后重试次数（再回退 mock）

    # 真实 HTTP provider 接入参数
    video_api_base: str = ""
    video_api_key: str = ""             # Bearer 模式用的 ARK API Key
    provider_timeout: float = 120.0     # 单次任务最长等待（秒）
    poll_interval: float = 3.0          # 轮询间隔（秒）

    # 火山视频模型
    volc_model: str = "doubao-seedance-2.0-260128"
    # volcano_seedance(Ark, Bearer) 用 video_api_key；volcano_legacy(旧OpenAPI, AK/SK) 用下面
    volc_ak: str = ""                  # legacy: AccessKey
    volc_sk: str = ""                  # legacy: SecretKey
    volc_region: str = "cn-beijing"
    volc_service: str = "ark"

    # mock 成本参数（用于 cost 系统演示）
    cost_per_mother: float = 1.0   # 每条母视频成本
    cost_per_clip: float = 0.1     # 每条裂变片段成本

    # B2：本地视频存储（本地+CDN 双存，download_url 优先本地，根治 24h 过期）
    storage_enabled: bool = False  # ECS 生产置 true（.env），dev/mock 默认 false 不发起下载
    storage_dir: str = "/opt/v4-video-engine/storage/videos"
    # nginx serve 该目录的静态访问基址，如 https://video.beautypeaceai.com/static/videos
    storage_base_url: str = ""

    # B5：分镜脚本生成 script_provider: rule(默认,无依赖) | llm(OpenAI兼容,如DeepSeek/通义)
    script_provider: str = "rule"
    llm_api_base: str = ""              # 如 https://api.deepseek.com/v1
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"

    # Patch2：上传
    upload_dir: str = "/opt/v4-video-engine/uploads"
    upload_base_url: str = ""           # nginx serve，如 https://video.beautypeaceai.com/static/uploads
    max_image_mb: int = 10
    max_video_mb: int = 500

    # V4 P0：批量上传 / 文档 / 批次上限
    max_doc_mb: int = 50                 # doc/docx/zip 单个上限
    max_batch_count: int = 10            # 每类（image/video/file）单批最多文件数
    max_batch_total_gb: float = 2.0      # 单批总量上限（防撑爆 ECS）
    zip_max_entries: int = 1000          # zip 列条目数上限（防 zip bomb）
    zip_max_total_mb: int = 500          # zip 解压后总大小上限（防 zip bomb）

    # V4 P0：临时存储保留与清理（天；0=不自动过期，需手动删）
    mother_retention_days: int = 0       # A台母视频：默认长期保留，可手动删
    viral_retention_days: int = 5        # B台裂变视频：5 天临时
    upload_retention_days: int = 7       # 上传素材：7 天临时

    # V4 P0：批量裂变与 A台防误触上限
    b_batch_total_limit: int = 50        # 单次批量裂变总产出硬上限（P0=50）
    max_a_batch: int = 10                # 一句话/单次最多生成母视频数（防火山误触）

    # V4 P0-A：A台真实生成熔断锁（RISK-1）。默认锁住，仅 .env 设 true 才允许真生成。
    enable_compose: bool = False         # false=生成通道维护中，preview 仍可用
    # V4 P0-B：compose / Seedance 标准参数（导演引擎统一注入；不散落硬编码）
    compose_ratio: str = "9:16"          # 竖版（美业默认）
    compose_resolution: str = "1080p"    # 高清
    compose_generate_audio: bool = True  # Seedance 原生音频
    compose_watermark: bool = False
    compose_max_images: int = 9          # 1 张首帧 + 最多 8 张参考图
    compose_seg_seconds: int = 4         # 导演分镜每段约 4 秒（拆段用）
    compose_seg_max_chars: int = 800     # 单段 Seedance text 上限（按单段控，非整条）

    # V4 P1.1：B台短视频裂变（Remixer 重编码 + QA）。生产默认短视频 [25,35]/1080x1920；
    # 测试可调小以加速（不影响生产口径）。
    b_remix_target_lo: float = 25.0      # 裂变输出目标时长下限（秒）
    b_remix_target_hi: float = 35.0      # 裂变输出目标时长上限（秒）
    b_remix_duration_tol: float = 0.5    # duration_check 容差
    b_remix_width: int = 1080
    b_remix_height: int = 1920
    b_remix_fps: int = 30
    b_remix_max_retry: int = 2           # QA 失败自动重试上限

    # V4 P2B-A：主题驱动 L2 执行计划（Dry-run）。默认关闭，不影响现有系统；
    # staging 验证时临时置 true；production 禁止开启。开启后才暴露 /api/p2b/*。
    enable_l2_skills: bool = False
    p2b_plan_version: str = "p2b_a_v1"   # 执行计划版本（幂等唯一键的一部分）

    # V4 P2B-B1：小批量真实执行（脑子→执行器→成片）。默认关闭；仅 staging + 开关 才允许真实生成；
    # production 强制 403（优先级最高，即使 flag=true）。单次最多 6 条。
    enable_p2b_real_execution: bool = False
    p2b_b1_max_items: int = 6            # 单 run 最多执行条数（B1 上限）
    p2b_b1_defect_source_ids: list[int] = [60]  # 已知缺陷源（禁用作为执行源），如 60 号

    # V4 P2B-B2：业务可见层（字幕/高光卡/CTA）。默认开；可临时关做 A/B 对照（不放宽任何安全闸门）。
    # 仅控制叠加层是否尝试渲染，关闭=回到 B1 纯底座成片。字体缺失时自动降级（不崩主流程）。
    enable_p2b_visible_layer: bool = True
    p2b_subtitle_font_path: str = ""    # 中文字体绝对路径（最高优先；空则走候选路径 + fc-match）

    # V4 P2B-B2.1：可见层逐 variant 确定性差异化（ASS 档位）。默认开；关=回 B2 固定 ASS 版式，
    # 不影响 subtitle/highlight/CTA 可见、不影响 B2 收口能力、不放宽任何安全闸门。
    enable_p2b_visible_variation: bool = True

    # V4 P2B-B2.5：音频/编码合规差异化（响度规范化 + 逐 variant 轻 EQ + metadata 清理 + 诚实溯源）。
    # 默认开；production 永不触发（runs 403）；关=回 B2.1 音频/编码口径，不影响 B1/B2/B2.1。
    enable_p2b_audio_encoding_diff: bool = True
    p2b_loudness_target_lufs: float = -14.0   # EBU R128 目标响度
    p2b_true_peak_dbtp: float = -1.0          # True Peak 验收上限（最终 mp4 实测须 ≤ 此值）
    # V2 hotfix：内部 TP 目标收紧 + 安全限幅 headroom，抵消 AAC 编码后真峰回弹（仅 TP 内部参数）
    p2b_tp_internal_dbtp: float = -2.0        # loudnorm 内部 TP 目标（比验收线低，留余量）
    p2b_limiter_limit: float = 0.794          # alimiter 限幅（≈ -2 dBFS，给 AAC 留 headroom）
    p2b_build_commit: str = ""                # 诚实溯源用：本次部署 commit（ECS 部署时注入；空=unknown）

    # V4 P2B-B3：三维差异评分闸门（只评分，不自动重剪/不生成/不扩批）。默认开；production 永不触发（403）；
    # 关=不评分、不写 b3 字段，回 B2.5 收口态。零新增表：写 videos.meta.b3_score + run_items.qa_json.b3_batch。
    enable_p2b_b3_score: bool = True
    p2b_b3_version: str = "b3_v1"
    p2b_b3_vds_pass: float = 70.0             # pair VDS 过线
    p2b_b3_visual_floor: float = 0.12         # 视觉维最低阈（provisional，负样本到位前不锁定）
    p2b_b3_text_floor: float = 0.10           # 文本维最低阈（provisional）
    p2b_b3_kf_min_floor: float = 0.06         # 近重复关键帧下界（provisional）
    p2b_b3_visual_target: float = 0.35        # 视觉满分差异度（校准锚）
    p2b_b3_text_target: float = 0.30          # 文本满分差异度
    p2b_b3_audio_target: float = 0.50         # 音频满分差异度（辅助维，目标低）
    p2b_b3_keyframes: int = 8                 # 关键帧抽样数 K
    p2b_b3_audio_switch_low: float = 0.08     # 权重滞后：audio_distance_mean<low → 45/35/10/10
    p2b_b3_audio_switch_high: float = 0.12    # audio_distance_mean>high → 40/35/15/10；区间内保持上次
    p2b_b3_fullpair_max_n: int = 30           # N>此值 → 不做全量 O(N²)，走分桶+候选精算降级
    p2b_b3_calibration: str = "provisional"   # 负样本到位并定稿后改 "final"


settings = Settings()
