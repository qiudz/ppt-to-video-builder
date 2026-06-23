# PPT-to-Video Builder
# 幻灯片配音与字幕视频生成器

这是一个通用的 Python 命令行工具，用于将 **PDF 幻灯片** 或 **已导出的幻灯片图片目录**，配合语音克隆模型生成的配音，自动合成为带有高清硬字幕的演示视频。

项目重点解决以下问题：

- 幻灯片配音与字幕不同步
- 多段视频拼接后翻页卡顿
- FFmpeg 时间戳漂移导致音视频错位
- Windows 路径在 concat 文件中解析失败
- 文案修改后旧音频缓存被错误复用
- 超长字幕溢出画面
- 短句字幕频繁闪烁
- 超大分辨率图片导致 libx264 编码失败

---

## 1. 核心能力

### 1.1 一句一音频，物理时长硬锁定

脚本会将每页演讲稿切分为多个字幕短句，并为每个短句单独生成配音。

每张字幕图片的停留时间直接使用对应音频文件的真实物理时长，因此可以从底层保证：

- 字幕出现时间与音频时长一致
- 翻页节奏稳定
- 长视频中不容易产生累积漂移

---

### 1.2 智能短句合并，减少字幕闪烁

如果文案中出现：

```text
1. 核心架构，2. 业务流转，3. 系统集成
```

过短的句子会导致字幕频繁切换。脚本提供短句合并机制：

- `--min-subtitle-units`：低于该长度的短句会尝试合并
- `--max-subtitle-units`：合并后的最大字幕长度

默认配置：

```text
--min-subtitle-units 8
--max-subtitle-units 28
```

这样可以在字幕可读性和画面稳定性之间取得较好平衡。

---

### 1.3 TTS 文本规范化

脚本内置 `normalize_text_for_tts()`，会对技术类文本做适合语音合成的清洗，例如：

| 原始文本 | TTS 处理方向 |
|---|---|
| `CLAUDE.md` | `Claude MD` |
| `Next.js` | `Next js` |
| `CI/CD` | `C I C D` |
| `/init` | `斜杠 init` |
| `--help` | `参数 help` |
| `src/app/page.tsx` | 路径和后缀会被拆解为更适合朗读的形式 |

这可以减少 TTS 读出奇怪符号、爆音或不自然停顿的问题。

---

### 1.4 高清硬字幕绘制

字幕不是用 FFmpeg `drawtext` 或 ASS 滤镜实时渲染，而是使用 Pillow 直接绘制到图片上。

优点：

- 不依赖系统是否安装 libass
- 不受 FFmpeg 字体路径兼容性影响
- 硬字幕在所有播放器中表现一致

支持两种字幕样式：

| 样式 | 说明 |
|---|---|
| `stroke` | 白色文字 + 黑色描边，默认推荐 |
| `banner` | 半透明黑色底条 + 白色文字 |

同时支持：

- 自动缩小字号
- 多行字幕
- 超长字幕省略号截断
- 中英文字体兜底加载

---

### 1.5 大无声视频 + 大音轨 + 全局混流

脚本不会直接生成大量短视频片段再拼接，而是采用三阶段流程：

1. 生成所有带字幕的图片
2. 按音频真实时长拼接成一个大无声视频
3. 拼接所有音频为一个完整音轨
4. 最后执行一次全局音视频混流

这样可以显著降低：

- 视频片段拼接卡顿
- 播放器时间戳识别异常
- 尾帧卡死
- 音画逐渐不同步

---

### 1.6 FFmpeg CFR 时间戳重建

图片 concat 场景中，如果只在输出端使用 `-r 25`，容易造成时间戳不稳定。

本脚本使用 FFmpeg `fps=` 滤镜重建恒定帧率 CFR 时间戳，例如：

```text
fps=25
```

并配合最大分辨率限制与偶数宽高修正，提升 H.264 编码稳定性。

---

### 1.7 音频缓存 Hash 失效机制

脚本会根据以下信息生成音频缓存文件名：

- 页码
- 句子序号
- 原始字幕文本
- TTS 清洗后的文本
- 模型名称
- 推理步数
- 参考音频路径、大小、修改时间
- 参考音频逐字稿 Hash

只要文案、参考音频或关键参数发生变化，缓存文件名就会变化，从而自动重新生成音频，避免出现：

```text
字幕已经改了，但声音还是旧版本
```

同时也支持：

```bash
--force-rebuild
```

用于强制清理旧缓存并完全重建。

---

## 2. 项目文件说明

| 文件 | 作用 |
|---|---|
| `build_presentation.py` | 主脚本，将 PDF/图片 + 文案 + 参考音频合成为 MP4 视频 |
| `process_ppt.py` | 可选辅助脚本，用于从 PPTX 中提取备注，并通过 PowerPoint 导出 PDF |
| `requirements.txt` | 当前项目基础依赖 |
| `README.md` | 使用说明文档 |

---

## 3. 环境准备

### 3.1 系统依赖

脚本依赖以下外部命令行工具：

| 工具 | 用途 |
|---|---|
| FFmpeg | 拼接视频、拼接音频、最终混流 |
| Poppler / pdftoppm | 将 PDF 幻灯片转换为 PNG 图片 |

安装示例：

#### Windows

如果使用 Scoop：

```powershell
scoop install main/ffmpeg main/poppler
```

也可以手动安装 FFmpeg 和 Poppler，并将其 `bin` 目录加入系统 `PATH`。

#### macOS

```bash
brew install ffmpeg poppler
```

#### Ubuntu / Debian

```bash
sudo apt-get update
sudo apt-get install ffmpeg poppler-utils
```

---

### 3.2 Python 基础依赖

当前 `requirements.txt` 包含：

```text
Pillow>=9.0.0
soundfile>=0.10.0
numpy>=1.20.0
```

安装方式：

```bash
pip install -r requirements.txt
```

---

### 3.3 语音克隆模型依赖

配音阶段依赖 VoxCPM2 及其相关环境，例如 PyTorch、voxcpm 等。

推荐方式：

> 使用已经配置好的 VoxCPM2 / voxcpm2-voice-cloner 虚拟环境来运行本脚本。

示例：

```bash
/path/to/voxcpm-env/bin/python build_presentation.py ...
```

Windows 示例：

```powershell
C:\path\to\voxcpm-env\Scripts\python.exe build_presentation.py ...
```

如果你使用 `--cloner-dir`，脚本会尝试将该目录及其 `.venv` 下的 `site-packages` 加入 Python 路径。

---

## 4. 输入文件准备

### 4.1 方式一：使用 PDF 幻灯片

准备一个 PDF 文件，例如：

```text
slides.pdf
```

脚本会自动调用 `pdftoppm` 将 PDF 转换为图片。

---

### 4.2 方式二：使用已导出的图片目录

也可以提前将幻灯片导出为图片，并按以下格式命名：

```text
page-1.png
page-2.png
page-3.png
```

或：

```text
page001.jpg
page002.jpg
page003.jpg
```

脚本会按文件名中的数字排序。

---

### 4.3 演讲文案格式

推荐使用 `---` 作为分页符，每一段对应一页幻灯片：

```text
大家好，今天我要介绍的是自动化幻灯片视频生成流程。
这个流程可以将文案、语音和字幕自动同步。
---
首先，我们来看整体架构。
整个流程分为幻灯片转换、语音克隆、字幕绘制和最终混流。
---
最后，我们总结一下。
这套方案可以减少人工剪辑，提高课件视频制作效率。
```

如果文案中没有 `---`，脚本会默认每个非空行对应一页幻灯片。

---

## 5. 可选：从 PPTX 提取备注并导出 PDF

如果你的演讲稿写在 PPTX 的备注中，可以先使用：

```bash
python process_ppt.py input.pptx output.pdf output_notes.txt
```

该脚本会：

1. 读取 PPTX 每页备注
2. 将备注写入 `output_notes.txt`
3. 通过 PowerPoint COM 接口导出 PDF

注意：

- 该流程主要适用于 Windows
- 需要本机安装 Microsoft PowerPoint
- 脚本会优先尝试 `win32com.client`
- 如果失败，会尝试 `comtypes.client`

之后可以将生成的 PDF 和备注文本传给主脚本：

```bash
python build_presentation.py \
  --pdf output.pdf \
  --texts-file output_notes.txt \
  --voice-ref ref_voice.wav \
  --prompt-file prompt.txt \
  --output final_video.mp4
```

---

## 6. 快速开始

### 6.1 PDF 输入示例

```bash
python build_presentation.py \
  --pdf slides.pdf \
  --texts-file texts.txt \
  --voice-ref ref_voice.wav \
  --prompt-file prompt.txt \
  --output output.mp4 \
  --cloner-dir /path/to/voxcpm2-voice-cloner \
  --fps 25 \
  --max-video-width 1920 \
  --max-video-height 1080
```

---

### 6.2 图片目录输入示例

```bash
python build_presentation.py \
  --images-dir ./pages \
  --texts-file texts.txt \
  --voice-ref ref_voice.wav \
  --prompt-file prompt.txt \
  --output output.mp4 \
  --cloner-dir /path/to/voxcpm2-voice-cloner
```

---

### 6.3 Windows 示例

```powershell
python build_presentation.py `
  --pdf "C:/Users/YourName/Downloads/slides.pdf" `
  --texts-file "C:/Users/YourName/Downloads/texts.txt" `
  --cloner-dir "C:/Users/YourName/Projects/voxcpm2-voice-cloner" `
  --voice-ref "C:/Users/YourName/Projects/voxcpm2-voice-cloner/voices/ref_voice.wav" `
  --prompt-file "C:/Users/YourName/Projects/voxcpm2-voice-cloner/voices/prompt.txt" `
  --output "C:/Users/YourName/Downloads/output.mp4" `
  --fps 25 `
  --max-video-width 1920 `
  --max-video-height 1080
```

---

## 7. 参数说明

### 7.1 输入输出参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `--pdf` | 否 | - | 输入 PDF 幻灯片路径，与 `--images-dir` 二选一 |
| `--images-dir` | 否 | - | 已导出的幻灯片图片目录 |
| `--texts-file` | 是 | - | 演讲文案文本路径，支持 `---` 分页 |
| `--output` | 是 | - | 输出 MP4 视频路径 |

---

### 7.2 语音克隆参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `--cloner-dir` | 否 | - | VoxCPM2 语音克隆器项目根路径 |
| `--voice-ref` | 是 | - | 参考音频 WAV 路径 |
| `--prompt-file` | 否 | - | 参考音频对应逐字稿文件 |
| `--prompt-text` | 否 | - | 参考音频对应逐字稿文本 |
| `--model-name` | 否 | `openbmb/VoxCPM2` | 模型名称 |
| `--timesteps` | 否 | `50` | 音频合成推理步数 |
| `--device` | 否 | 自动检测 | 指定推理设备，例如 `cuda`、`mps`、`cpu` |

---

### 7.3 字幕参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `--font-path` | 否 | 系统默认 | 字幕字体路径 |
| `--font-size` | 否 | `55` | 字幕基础字号 |
| `--bottom-margin` | 否 | `50` | 字幕距离底部的像素距离 |
| `--subtitle-style` | 否 | `stroke` | 字幕样式：`stroke` 或 `banner` |
| `--stroke-width` | 否 | `3` | 描边宽度，仅 `stroke` 样式有效 |
| `--rect-height` | 否 | `110` | 字幕底条高度，仅 `banner` 样式有效 |
| `--rect-alpha` | 否 | `140` | 字幕底条透明度，仅 `banner` 样式有效 |
| `--subtitle-max-lines` | 否 | `2` | 字幕最大行数，超出后截断 |
| `--min-subtitle-units` | 否 | `8` | 短字幕合并阈值 |
| `--max-subtitle-units` | 否 | `28` | 合并后字幕最大长度 |

---

### 7.4 视频参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `--fps` | 否 | `25` | 输出视频恒定帧率 |
| `--max-video-width` | 否 | `1920` | 输出最大宽度，超出后等比缩小 |
| `--max-video-height` | 否 | `1080` | 输出最大高度，超出后等比缩小 |

---

### 7.5 缓存与运行控制参数

| 参数 | 必填 | 默认值 | 说明 |
|---|---:|---|---|
| `--workdir` | 否 | `./workdir_video` | 工作缓存目录 |
| `--force-rebuild` | 否 | `False` | 强制清理旧缓存并重建 |
| `--no-cleanup` | 否 | `False` | 保留临时字幕图片等中间文件 |

---

## 8. 缓存机制说明

默认情况下，脚本会复用已生成的音频缓存，以便中断后继续执行。

但音频缓存文件名中包含 Hash 指纹。以下内容变化时，会自动生成新的音频：

- 字幕原文
- TTS 清洗后的文本
- 模型名称
- 推理步数
- 参考音频文件大小或修改时间
- 参考音频逐字稿内容

如果希望完全清理缓存，可加：

```bash
--force-rebuild
```

示例：

```bash
python build_presentation.py \
  --pdf slides.pdf \
  --texts-file texts.txt \
  --voice-ref ref_voice.wav \
  --prompt-file prompt.txt \
  --output output.mp4 \
  --force-rebuild
```

---

## 9. 常见问题与排查

### 9.1 提示找不到 `pdftoppm`

说明系统未安装 Poppler，或 Poppler 未加入 PATH。

解决：

```bash
brew install poppler
```

或：

```bash
sudo apt-get install poppler-utils
```

Windows 请确认 Poppler 的 `bin` 目录已加入系统 PATH。

---

### 9.2 提示找不到 `ffmpeg`

说明 FFmpeg 未安装，或未加入 PATH。

检查：

```bash
ffmpeg -version
```

如果不能输出版本信息，请先安装 FFmpeg。

---

### 9.3 文案改了，但声音没有变化

正常情况下，Hash 缓存会自动失效。

如果仍怀疑缓存被复用，可以强制重建：

```bash
--force-rebuild
```

或者删除：

```text
workdir_video/audio_subs
```

---

### 9.4 视频末尾卡住或音画不同步

建议确认使用新版脚本中的 `fps=` 滤镜逻辑，并保持：

```bash
--fps 25
```

如果仍有问题，可尝试：

```bash
--fps 30
```

---

### 9.5 图片太大导致 FFmpeg 编码失败

如果 PDF 导出的图片分辨率过大，建议限制输出最大尺寸：

```bash
--max-video-width 1920 --max-video-height 1080
```

如果需要更高清，可尝试：

```bash
--max-video-width 2560 --max-video-height 1440
```

---

### 9.6 字幕太长显示不完整

可以尝试：

```bash
--subtitle-max-lines 3
```

或减小字号：

```bash
--font-size 46
```

也可以适当调大字幕区域：

```bash
--rect-height 150
```

---

### 9.7 字幕闪烁太频繁

增大短句合并阈值：

```bash
--min-subtitle-units 10 --max-subtitle-units 32
```

如果希望更短、更快的字幕节奏，可以降低：

```bash
--min-subtitle-units 6
```

---

### 9.8 中文字体显示异常

请显式指定字体路径。

Windows 示例：

```bash
--font-path "C:/Windows/Fonts/msyh.ttc"
```

macOS 示例：

```bash
--font-path "/System/Library/Fonts/STHeiti Medium.ttc"
```

Linux 示例：

```bash
--font-path "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
```

---

## 10. 推荐工作流

### 10.1 从 PPTX 到视频

```text
PPTX
  ↓
process_ppt.py 提取备注并导出 PDF
  ↓
PDF + notes.txt
  ↓
build_presentation.py
  ↓
MP4 演示视频
```

示例：

```bash
python process_ppt.py demo.pptx demo.pdf demo_notes.txt

python build_presentation.py \
  --pdf demo.pdf \
  --texts-file demo_notes.txt \
  --voice-ref ref_voice.wav \
  --prompt-file prompt.txt \
  --output demo_video.mp4
```

---

### 10.2 从 PDF 到视频

```text
PDF
  ↓
build_presentation.py 自动转图片
  ↓
生成字幕图、音频、无声视频、完整音轨
  ↓
全局混流输出 MP4
```

---

### 10.3 从图片目录到视频

```text
page-1.png
page-2.png
page-3.png
  ↓
build_presentation.py
  ↓
MP4
```

---

## 11. 最佳实践

### 11.1 文案建议

推荐：

```text
我们首先看整体架构。系统分为输入层、处理层和输出层。
```

不推荐过度碎片化：

```text
输入层，处理层，输出层，三个部分。
```

如果短句太多，字幕会频繁切换。

---

### 11.2 技术词建议

对于技术名词，可以直接写：

```text
Next.js、API、CI/CD、CLAUDE.md
```

脚本会尽量转换为适合 TTS 的读法。

---

### 11.3 分页建议

每页文案尽量控制在一个自然讲解段落内。

如果某页文案过长，建议拆成多页，视频观看体验会更好。

---

## 12. 输出文件说明

默认工作目录：

```text
workdir_video/
```

常见中间文件：

| 文件或目录 | 说明 |
|---|---|
| `temp_subs/` | 临时字幕图片 |
| `audio_subs/` | 分句音频缓存 |
| `concat_videos_silent.txt` | FFmpeg 无声视频 concat 列表 |
| `concat_audios.txt` | FFmpeg 音频 concat 列表 |
| `final_silent.mp4` | 大无声视频 |
| `final_audio.wav` | 拼接后的完整音轨 |

如果不加 `--no-cleanup`，脚本结束后会自动清理临时字幕图片目录。

---

## 13. 许可证

MIT License
