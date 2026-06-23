# PPT-to-Video Builder (幻灯片配音与字幕视频生成器)

这是一个通用的独立 Python 命令行工具，旨在将 PDF 幻灯片（或图片文件夹）配合克隆的语音配音，全自动合成为带有**高清大字号自适应滚动字幕**的演示视频。

本项目解决了传统 AI 视频合成中“音字不同步”以及“多段视频拼接导致翻页延迟卡顿”的技术痛点。

---

## 核心设计原理与架构

为了提供 100% 精确同步与极致流畅的观看体验，本项目实现了以下核心技术架构：

### 1. 物理锁定对齐（分句音频时长对齐）
- **传统问题**：按页整体生成音频并用算法等分时长容易导致中英文发音、呼吸停顿和句尾白噪带来的音字错位。
- **解决方案**：将整页长文案智能切分为有意义的**字幕短句**（通常 10-25 字，忽略纯标点，逗号句号合并）。为每一小句单独调用克隆模型生成短音频，并读取其实际物理长度。画面上该字幕的停留时间直接被硬锁定为这句音频的精确物理时长，从底层确保 **100% 毫秒级绝对音字同步**。

### 2. Pillow 高清自适应硬字幕绘制
- **传统问题**：使用 `ffmpeg` 的 `drawtext` 或 `ass` 滤镜极易因环境缺失 `libass` 库或字体文件路径错误引发兼容性报错。
- **解决方案**：直接使用 Pillow 库在原图底部上方绘制半透明黑底白字的高清字幕。
  - **默认规格**：在 `5334 x 3000` 画质下，基础字号设为 `240`，黑色遮罩高度为 `360`，居底部距离为 `120`。
  - **溢出保护**：当单行字幕宽度超过安全界限（图片宽度 - 400）时，算法将自动等比逐级缩小字号（240px -> 220px -> 200px...），以防止画面字符截断。

### 3. 大视频/音轨独立拼接 + 全局混流
- **传统问题**：直接拼接上百个细碎的“有声视频片段”时，会在不同播放器里因时间戳累积偏差造成画面切换严重延迟卡顿。
- **解决方案**：重构为“独立拼接大无声视频” + “独立拼接大音轨” + “全局一次性混流”的机制。将所有带字幕的页面按精准时长利用 `ffmpeg concat` 拼接为一个整的无声视频 `final_silent.mp4`，再把所有配音拼接为完整音轨 `final_audio.wav`，最后在末尾执行一次全局混流，从而保证翻页顺滑无比，零卡顿。

---

## 环境准备

### 1. 系统依赖
- **FFmpeg**: 用于音视频的拼接与最终混流。
- **Poppler** (提供 `pdftoppm`): 用于将 PDF 幻灯片快速转换为超高清图片。
  - **macOS**: `brew install poppler ffmpeg`
  - **Ubuntu/Debian**: `sudo apt-get install poppler-utils ffmpeg`

### 2. Python 依赖
本项目本身运行依赖 Pillow 和 soundfile。但由于在配音阶段需要加载 `VoxCPM2` 声音克隆大模型及相关依赖（如 PyTorch），**最简便的运行方式是直接使用已配置好的 `voxcpm2-voice-cloner` 虚拟环境的 Python 解释器运行此脚本。**

如果您想单独部署，可以直接在当前目录下创建虚拟环境并安装：
```bash
pip install -r requirements.txt
```

---

## 快速开始

### 1. 准备您的演讲文案
新建一个文案文本文件（例如 `my_presentation_texts.txt`），通过 `---` 独占一行作为不同幻灯片的分页符：
```text
大家好，今天我要给大家介绍的，正在改变开发者世界的工具——Claude Code。
过去一两年，大家可能用过 GitHub Copilot。但今天我们要讲的 Claude Code 完全不同。
---
首先，我们进入第一部分：认知升级。在使用 Claude Code 之前，我们必须先放下以前使用 AI 工具的固有思维。
---
最后，我想用一句话结束今天的分享：不要仅仅将 Claude Code 视为一个聪明的工具，请将它视作结对编程的高级工程师。
```

### 2. 运行合成命令
直接使用已安装好的语音克隆工具的 Python 环境来运行：

```bash
/Users/xiang/Code/AI/voxcpm2-voice-cloner/.venv/bin/python build_presentation.py \
  --pdf "/Users/xiang/Downloads/Claude Code入门介绍.pdf" \
  --texts-file "my_presentation_texts.txt" \
  --cloner-dir "/Users/xiang/Code/AI/voxcpm2-voice-cloner" \
  --voice-ref "/Users/xiang/Code/AI/voxcpm2-voice-cloner/voices/仇佃祥/ref_voice.wav" \
  --prompt-file "/Users/xiang/Code/AI/voxcpm2-voice-cloner/voices/仇佃祥/prompt.txt" \
  --output "/Users/xiang/Downloads/My_Cloned_Presentation_Video.mp4"
```

### 3. 主要参数说明

| 参数 | 必填 | 默认值 | 描述 |
| :--- | :---: | :---: | :--- |
| `--pdf` | 否 | - | 输入的 PDF 幻灯片文件路径（与 `--images-dir` 二选一） |
| `--images-dir` | 否 | - | 已有的幻灯片图片目录（以 `page-` 开头的 PNG/JPG 文件） |
| `--texts-file` | **是** | - | 演讲文案文本文件路径，支持用 `---` 独立行分页 |
| `--output` | **是** | - | 最终合成的高清 MP4 视频路径 |
| `--cloner-dir` | 否 | - | 语音克隆器项目的根路径（用于动态载入 `voxcpm` 模块） |
| `--voice-ref` | **是** | - | 克隆所用参考配音的 `.wav` 文件路径 |
| `--prompt-file` | 否 | - | 参考配音对应的文字稿文件路径（首选） |
| `--prompt-text` | 否 | - | 参考配音对应的文字稿字符串内容（备选） |
| `--font-path` | 否 | `/System/Library/Fonts/STHeiti Medium.ttc` | 绘制字幕的中文字体路径 |
| `--font-size` | 否 | `240` | 字幕基础字号尺寸（支持自适应缩减以防超宽） |
| `--bottom-margin` | 否 | `120` | 字幕底框距离最下边的像素距离 |
| `--rect-height` | 否 | `360` | 半透明字幕框底条的高度 |
| `--rect-alpha` | 否 | `180` | 字幕底条的不透明度（0-255 之间，180 约为 0.7） |
| `--workdir` | 否 | `./workdir_video` | 临时文件缓存工作目录 |
| `--device` | 否 | - | 强制指定运行推理的设备 (`cuda`/`mps`/`cpu` 等) |
| `--timesteps` | 否 | `50` | 模型音频合成的推理步数 |
| `--no-cleanup` | 否 | `False` | 设置后将不自动删除临时渲染的单句字幕 PNG 图像 |

---

## 许可证
MIT License
