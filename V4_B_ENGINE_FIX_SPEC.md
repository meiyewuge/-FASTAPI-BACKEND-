# B台架构修正施工包

## 问题
当前 `b_engine/remixer.py` 调用 `provider.remix()`（走 FallbackProvider → 火山API），这是错误的。

**正确架构：**
- A台 = 豆包视频2.0（火山API），花钱出高质量母视频
- B台 = 纯本地ffmpeg裂变，**零AI API调用，零成本**

## 修正范围

### 1. `b_engine/remixer.py` — 重写核心逻辑
- 不再调用 `provider.remix()`
- 改为本地ffmpeg流水线：
  1. 接收母视频本地路径（非URL）
  2. ffmpeg切片（按策略分片，如每3-5秒一段）
  3. 重组 + 叠加策略文案（引流型/成交型/IP型/招商型/获客型）
  4. 可选：加字幕/水印/门店差异化
  5. 输出到 `/opt/v4-video-engine/storage/videos/viral/`

### 2. `services/b_service.py` — 改source_url为本地路径
- 当前：`source_url = source.cdn_url or source.download_url` → 传公网URL给火山
- 修正：取母视频本地文件路径（`/opt/v4-video-engine/storage/videos/mother/{id}.mp4`）
- 传给remixer的是本地路径，不是URL

### 3. 不再需要provider
- B台整个链路不经过 `utils/video_provider.py`
- 删除 remixer.py 中 `from utils.video_provider import get_provider`

### 4. ffmpeg依赖
- 已安装 v7.0.2（imageio-ffmpeg + 软链接）
- 注意：之前B台测试ffmpeg core dump是因为下载mock空文件，真实mp4不会

## 当前代码位置（ECS）
- `/opt/v4-video-engine/backend/b_engine/remixer.py`
- `/opt/v4-video-engine/backend/b_engine/strategies.py`
- `/opt/v4-video-engine/backend/services/b_service.py`
- `/opt/v4-video-engine/backend/utils/video_provider.py`（B台不再依赖）

## 五种策略（已有定义在 strategies.py）
引流型 / 成交型 / IP型 / 招商型 / 获客型
每种策略决定：切片节奏、文案叠加方式、结尾CTA

## 成本
B台修正后 = 纯本地ffmpeg处理，**0元/条**（不计API费用）

## 测试验证
修正后需验证：
1. 基于video_id=15（5秒720p真实mp4）生成1条裂变视频
2. ffmpeg不crash
3. 产出真实mp4到viral目录
4. API返回本地URL可下载
5. 封面图正常提取
