# ECS P0 补丁集成指南

> ⚠️ 本会话的 Claude **无法访问你的 ECS**（`/opt/v4-video-engine`，8.152.169.71）。
> 下列是**可落盘的补丁模块 + 集成步骤**，由你团队 / ECS 上的 Claude Code 应用。
> 所有机制已在沙箱**真验证**（ffmpeg 拼接、本地存储下载、B台视频输入请求体）。

## 涉及文件
| 动作 | 文件 | 作用 |
| --- | --- | --- |
| 新增 | `utils/video_storage.py` | 本地+CDN 双存（P0-1/2）|
| 新增 | `utils/url_refresh.py` | 签名 URL 过期检测/刷新（辅助）|
| 新增 | `services/composer.py` | 长视频切片编排 + FFmpeg 拼接（P0-3/5）|
| 改 | `config.py` | storage_*/segment_seconds 配置 |
| 改 | `models/video.py` | 增 `cdn_url` / `local_url` 列 |
| 改 | `services/a_service.py` | 生成后落本地，download_url 本地优先 |
| 改 | `services/b_service.py` | 同上 + B台视频输入用母视频 URL |
| 改 | `utils/volcano_doubao_provider.py` | B台请求体含视频输入（P0-4）|

## ECS 应用步骤
1. **取补丁**：把上述文件同步到 `/opt/v4-video-engine/backend/`
   （若 ECS 代码结构与本仓库分支一致，可直接覆盖/合并对应文件）。
2. **装 ffmpeg**：`apt-get install -y ffmpeg`（拼接必需）。
3. **DB 迁移**（SQLite，给 videos 加两列）：
   ```sql
   ALTER TABLE videos ADD COLUMN cdn_url   VARCHAR(1024);
   ALTER TABLE videos ADD COLUMN local_url VARCHAR(512);
   ```
4. **本地存储目录 + nginx 静态**（母/裂变分目录，代码会自动建 mother/ viral/）：
   ```
   mkdir -p /opt/v4-video-engine/storage/videos/{mother,viral}
   # nginx：location /static/videos/ { alias /opt/v4-video-engine/storage/videos/; }
   # 落盘：mother/{id}.mp4、viral/{id}.mp4
   ```
5. **.env 开启存储**：
   ```
   STORAGE_ENABLED=true
   STORAGE_DIR=/opt/v4-video-engine/storage/videos
   STORAGE_BASE_URL=https://video.beautypeaceai.com/static/videos
   SEGMENT_SECONDS=5
   ```
6. **B台视频输入字段校准**（重要）：`volcano_doubao_provider._submit` 里给视频输入用了
   `{"type":"image_url","image_url":{"url":...}}` 作占位。**你 ECS 的 B台「含视频输入」已跑通**，
   请用 ECS 实际生效的字段名替换（火山「含视频输入」API 文档为准），否则 B台会退回纯文生。
7. **重启**：`systemctl restart v4-video-engine`。

## 长视频「一次成型」接线
`composer.compose_long_video(tenant, prompt, total_seconds, seg_seconds, segment_generator=...)`
需注入 `segment_generator(tenant, seg_prompt, seconds) -> 本地mp4路径`，内部实现 = provider 生成该段
→ `video_storage.download_and_store` 取本地路径。然后 composer 自动 FFmpeg 拼接成完整片。
（切片规划与拼接已验证；并发可用 ThreadPoolExecutor 包 segment_generator。）

## 已验证（沙箱，真跑）
- `plan_segments(120,5)=24×5s`、`(120,15)=8×15s`
- FFmpeg 拼接 3×2s → 6.0s 成片（ffprobe 实测）
- 本地存储：HTTP 下载 mp4 → 落盘成功
- B台 `_submit` 请求体含 `image_url`(母视频 URL) + `text`(裂变指令)

## ⚠️ 两点须知（不在 P0 范围，备忘）
- **计费口径**：本分支 cost_engine 是「按条」，你 ECS 是「按秒」（A台1元/秒、B台0.57元/秒）。
  P0 要求「不改 cost_engine」，故未动；Git 回灌阶段需以 ECS 的按秒计费为准统一。
- **本地存储根治 URL 过期**：本地副本永不过期，`url_refresh` 仅作未落盘视频的兜底。
