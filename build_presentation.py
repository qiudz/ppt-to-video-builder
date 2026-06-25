#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import time
import re
import shutil
import argparse
import hashlib
import json
from PIL import Image, ImageDraw, ImageFont


def detect_device():
    """
    自动检测硬件加速设备。
    优先级：CUDA > XPU > MPS > CPU
    """
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"

        if hasattr(torch, "xpu") and torch.xpu.is_available():
            return "xpu"

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"

    except Exception:
        pass

    return "cpu"


def count_text_units(text):
    """
    估算字幕长度单位。
    中文按字计，连续英文/数字按一个词计。
    """
    if not text:
        return 0

    return len(re.findall(r"[\u4e00-\u9fa5]|[a-zA-Z0-9]+", str(text)))


def split_text_to_sentences(text, max_len=20, min_len=10):
    """
    智能将段落文案切分成有意义的字幕短句。
    会排除任何单独成句的标点符号。

    参数：
    - text: 原始段落
    - max_len: 单句最大建议字符数
    - min_len: 单句最小建议字符数
    """

    if not text:
        return []

    text = str(text).strip()
    if not text:
        return []

    raw_sentences = re.findall(r"[^，。？！；、,.?!;]+[，。？！；、,.?!;]*", text)

    sentences = []
    current = ""

    for s in raw_sentences:
        s = s.strip()
        if not s:
            continue

        # 如果只有标点，则合并到上一句
        if not re.search(r"[\u4e00-\u9fa5a-zA-Z0-9]", s):
            if sentences:
                sentences[-1] += s
            elif current:
                current += s
            continue

        current += s

        char_count = count_text_units(current)
        if char_count >= min_len:
            sentences.append(current.strip())
            current = ""

    if current:
        if sentences:
            sentences[-1] += current
        else:
            sentences.append(current.strip())

    final_sentences = []

    for s in sentences:
        char_count = count_text_units(s)

        if char_count > max_len:
            subparts = re.findall(r"[^，、, ]+[，、, ]*", s)
            sub_current = ""

            for sp in subparts:
                sub_current += sp
                sub_char = count_text_units(sub_current)

                if sub_char >= min_len:
                    final_sentences.append(sub_current.strip())
                    sub_current = ""

            if sub_current:
                if final_sentences:
                    final_sentences[-1] += sub_current
                else:
                    final_sentences.append(sub_current.strip())
        else:
            final_sentences.append(s.strip())

    cleaned = []

    for s in final_sentences:
        s = s.strip()

        if not s:
            continue

        if re.search(r"[\u4e00-\u9fa5a-zA-Z0-9]", s):
            cleaned.append(s)
        else:
            if cleaned:
                cleaned[-1] += s

    return cleaned


def merge_too_short_sentences(sentences, min_units=8, max_units=28):
    """
    合并过短字幕，避免因短句过多造成画面底部字幕高频闪烁。

    逻辑：
    - 当前句过短时，优先和下一句合并
    - 合并后不超过 max_units 才合并
    - 最后一条过短时，尝试并入上一条
    """

    if not sentences:
        return []

    merged = []
    buffer = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if not buffer:
            buffer = sentence
        else:
            candidate = buffer + sentence

            if count_text_units(buffer) < min_units and count_text_units(candidate) <= max_units:
                buffer = candidate
            else:
                merged.append(buffer)
                buffer = sentence

    if buffer:
        if merged and count_text_units(buffer) < min_units:
            candidate = merged[-1] + buffer

            if count_text_units(candidate) <= max_units:
                merged[-1] = candidate
            else:
                merged.append(buffer)
        else:
            merged.append(buffer)

    return merged


def normalize_text_for_tts(text):
    """
    针对语音合成 TTS 的文本清洗与发音优化。

    目标：
    1. 删除 $$...$$ 这类讲师动作提示
    2. 避免代码符号、路径、文件后缀、命令导致 TTS 爆音
    3. 将常见技术缩写拆成更适合朗读的形式
    4. 尽量保留中文业务语义
    """

    if not text:
        return ""

    text = str(text)

    # 1. 删除 $$...$$ 动作提示
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.S)

    # 2. 删除 Markdown 代码块，保留行内代码内容
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)

    # 3. 常见技术词、产品名、缩写、文件名特殊处理
    replacements = {
        r"\bCLAUDE\.md\b": "CLAUDE 点 md",
        r"\bClaude\.md\b": "CLAUDE 点 md",
        r"\bNext\.js\b": "Next js",
        r"\bNode\.js\b": "Node js",
        r"\bVue\.js\b": "Vue js",
        r"\bReact\.js\b": "React js",
        r"\bTypeScript\b": "Type Script",
        r"\bJavaScript\b": "Java Script",
        r"\bGitHub\b": "Git Hub",
        r"\bGitLab\b": "Git Lab",
        r"\bPowerShell\b": "Power Shell",
        r"\bPowerPoint\b": "Power Point",
        r"\bPower Automate\b": "Power Automate",
        r"\bCI/CD\b": "C I C D",
        r"\bCICD\b": "C I C D",
        r"\bAPI\b": "A P I",
        r"\bSDK\b": "S D K",
        r"\bCLI\b": "C L I",
        r"\bUI\b": "U I",
        r"\bUX\b": "U X",
        r"\bURL\b": "U R L",
        r"\bURI\b": "U R I",
        r"\bHTTP\b": "H T T P",
        r"\bHTTPS\b": "H T T P S",
        r"\bJSON\b": "J S O N",
        r"\bXML\b": "X M L",
        r"\bSQL\b": "S Q L",
        r"\bCSV\b": "C S V",
        r"\bPDF\b": "P D F",
        r"\bHTML\b": "H T M L",
        r"\bCSS\b": "C S S",
        r"\bAI\b": "A I",
        r"\bLLM\b": "L L M",
        r"\bRAG\b": "R A G",
        r"\bGPU\b": "G P U",
        r"\bCPU\b": "C P U",
        r"\bNPU\b": "N P U",
        r"\bRAM\b": "R A M",
        r"\bOCR\b": "O C R",
        r"\bTTS\b": "T T S",
        r"\bASR\b": "A S R",
        r"\bSOP\b": "S O P",
        r"\bERP\b": "E R P",
        r"\bCRM\b": "C R M",
        r"\bWMS\b": "W M S",
        r"\bMES\b": "M E S",
        r"\bOA\b": "O A",
    }

    for pattern, repl in replacements.items():
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    # 4. 常见命令优先处理
    command_replacements = {
        r"\brm\s+-rf\b": "rm rf",
        r"\bsudo\b": "sudo",
        r"\bnpm\s+install\b": "npm install",
        r"\bnpm\s+run\b": "npm run",
        r"\bpnpm\s+install\b": "pnpm install",
        r"\byarn\s+install\b": "yarn install",
        r"\bgit\s+clone\b": "git clone",
        r"\bgit\s+commit\b": "git commit",
        r"\bgit\s+push\b": "git push",
        r"\bgit\s+pull\b": "git pull",
        r"\bgit\s+checkout\b": "git checkout",
        r"\bgit\s+merge\b": "git merge",
        r"\bgit\s+rebase\b": "git rebase",
    }

    for pattern, repl in command_replacements.items():
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

    # 5. 处理斜杠命令
    # /init -> 斜杠 init
    text = re.sub(r"(?<!\w)/([a-zA-Z0-9_\-]+)", r" 斜杠 \1 ", text)

    # 6. 处理命令参数
    # --help -> 参数 help
    # -v -> 参数 v
    text = re.sub(r"--([a-zA-Z0-9_\-]+)", r" 参数 \1 ", text)
    text = re.sub(r"(?<!\w)-([a-zA-Z])\b", r" 参数 \1 ", text)

    # 7. 处理 @引用
    text = text.replace("@", " ")

    # 8. 处理路径分隔符
    text = text.replace("\\", " 反斜杠 ")
    text = re.sub(r"[/]+", " ", text)

    # 9. 文件后缀统一处理，长后缀优先
    suffix_map = {
        ".dockerfile": " Dockerfile",
        ".gitignore": " Git Ignore",
        ".env": " ENV",
        ".tsx": " TSX",
        ".jsx": " JSX",
        ".yaml": " YAML",
        ".yml": " YAML",
        ".json": " JSON",
        ".html": " HTML",
        ".scss": " SCSS",
        ".pptx": " PowerPoint",
        ".docx": " Word",
        ".xlsx": " Excel",
        ".jpeg": " JPEG",
        ".md": " MD",
        ".txt": " TXT",
        ".ts": " TS",
        ".js": " JS",
        ".py": " Python",
        ".java": " Java",
        ".go": " Go",
        ".rs": " Rust",
        ".css": " CSS",
        ".sql": " SQL",
        ".csv": " CSV",
        ".xls": " Excel",
        ".ppt": " PowerPoint",
        ".doc": " Word",
        ".pdf": " PDF",
        ".wav": " WAV",
        ".mp3": " MP3",
        ".mp4": " MP4",
        ".png": " PNG",
        ".jpg": " JPG",
        ".zip": " ZIP",
        ".rar": " RAR",
        ".7z": " 7 Z",
    }

    for suffix, repl in sorted(suffix_map.items(), key=lambda x: len(x[0]), reverse=True):
        text = re.sub(re.escape(suffix) + r"\b", repl, text, flags=re.IGNORECASE)

    # 10. 处理版本号、小数点
    # v2.0 -> v2 点 0
    # 1.5 -> 1 点 5
    text = re.sub(r"(?<=\d)\.(?=\d)", " 点 ", text)

    # 11. 处理常见符号
    text = text.replace("_", " ")
    text = text.replace("=", " 等于 ")
    text = text.replace("+", " 加 ")
    text = text.replace("&", " 和 ")
    text = text.replace("%", " 百分号 ")

    symbol_map = {
        "#": " ",
        "*": " ",
        "~": " ",
        "^": " ",
        "$": " ",
        "|": " ",
        ">": " ",
        "<": " ",
        "[": " ",
        "]": " ",
        "{": " ",
        "}": " ",
        "(": " ",
        ")": " ",
        "（": " ",
        "）": " ",
        "【": " ",
        "】": " ",
        "「": " ",
        "」": " ",
        "『": " ",
        "』": " ",
    }

    for k, v in symbol_map.items():
        text = text.replace(k, v)

    # 12. 清理中英文引号
    text = (
        text.replace("‘", "")
        .replace("’", "")
        .replace("“", "")
        .replace("”", "")
        .replace('"', "")
        .replace("'", "")
    )

    # 13. 连续破折号、减号处理
    text = re.sub(r"[-—–]+", " ", text)

    # 14. 标点规范化
    text = re.sub(r"[;,]+", "，", text)
    text = re.sub(r"[.]+", "。", text)
    text = re.sub(r"[:：]{2,}", "：", text)

    # 15. 合并空格和重复标点
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"，+", "，", text)
    text = re.sub(r"。+", "。", text)
    text = re.sub(r"！+", "！", text)
    text = re.sub(r"？+", "？", text)

    return text.strip()


def stable_short_hash(payload, length=10):
    """
    生成稳定短 hash，用于音频缓存失效。
    """
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def get_file_fingerprint(path):
    """
    获取文件指纹。
    用于判断参考音频是否发生变化。
    """
    if not path or not os.path.exists(path):
        return {
            "path": path,
            "exists": False,
        }

    stat = os.stat(path)

    return {
        "path": os.path.abspath(path).replace("\\", "/"),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def build_audio_cache_name(slide_num, sentence_idx, sentence, tts_text, args, ref_voice_text):
    """
    构建带 hash 的音频缓存文件名。
    这样 texts_file 内容变化后，不会误用旧音频。
    """

    payload = {
        "slide_num": slide_num,
        "sentence_idx": sentence_idx,
        "sentence": sentence,
        "tts_text": tts_text,
        "model_name": args.model_name,
        "timesteps": args.timesteps,
        "voice_ref": get_file_fingerprint(args.voice_ref),
        "prompt_text_hash": hashlib.sha1(ref_voice_text.encode("utf-8")).hexdigest(),
    }

    h = stable_short_hash(payload, length=10)

    return f"audio_{slide_num:02d}_{sentence_idx:02d}_{h}.wav"


def load_font_safely(font_path, font_size):
    """
    安全加载字体。
    如果指定字体不存在，则尽量使用系统常见中文字体。
    """

    candidate_fonts = []

    if font_path:
        candidate_fonts.append(font_path)

    if os.name == "nt":
        candidate_fonts.extend([
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\simsun.ttc",
        ])
    else:
        candidate_fonts.extend([
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ])

    for fp in candidate_fonts:
        if fp and os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, font_size)
            except Exception:
                continue

    return ImageFont.load_default()


def measure_text(draw, text, font, stroke_width=0):
    """
    测量文本宽高。
    """
    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font,
        stroke_width=stroke_width,
    )
    return bbox, bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text_by_width(draw, text, font, max_width, max_lines=2, stroke_width=0):
    """
    按像素宽度对字幕做简单换行。
    若超过 max_lines，则最后一行用省略号截断。
    """

    if not text:
        return [""]

    chars = list(text)
    lines = []
    current = ""
    used_chars = 0

    for ch in chars:
        test_line = current + ch
        _, test_width, _ = measure_text(draw, test_line, font, stroke_width=stroke_width)

        if test_width <= max_width:
            current = test_line
            used_chars += 1
        else:
            if current:
                lines.append(current)
                current = ch
                used_chars += 1
            else:
                lines.append(ch)
                current = ""
                used_chars += 1

            if len(lines) >= max_lines:
                break

    if current and len(lines) < max_lines:
        lines.append(current)

    joined_len = sum(len(line) for line in lines)

    if joined_len < len(text) and lines:
        ellipsis = "…"
        last = lines[-1]

        while last:
            test_line = last + ellipsis
            _, test_width, _ = measure_text(draw, test_line, font, stroke_width=stroke_width)

            if test_width <= max_width:
                lines[-1] = test_line
                break

            last = last[:-1]

        if not last:
            lines[-1] = ellipsis

    return lines


def prepare_subtitle_lines(
    draw,
    text,
    font_path,
    image_width,
    font_size,
    min_font_size=28,
    horizontal_margin=100,
    max_lines=2,
    stroke_width=3,
):
    """
    自动准备字幕行：
    1. 优先使用原字号
    2. 若一行放不下，尝试换行
    3. 若仍不理想，逐步缩小字号
    4. 最后兜底截断
    """

    max_width = max(100, image_width - horizontal_margin * 2)
    current_size = font_size

    while current_size >= min_font_size:
        font = load_font_safely(font_path, current_size)

        lines = wrap_text_by_width(
            draw=draw,
            text=text,
            font=font,
            max_width=max_width,
            max_lines=max_lines,
            stroke_width=stroke_width,
        )

        too_wide = False

        for line in lines:
            _, line_width, _ = measure_text(draw, line, font, stroke_width=stroke_width)
            if line_width > max_width:
                too_wide = True
                break

        if not too_wide:
            return font, lines

        current_size -= 2

    font = load_font_safely(font_path, min_font_size)

    lines = wrap_text_by_width(
        draw=draw,
        text=text,
        font=font,
        max_width=max_width,
        max_lines=max_lines,
        stroke_width=stroke_width,
    )

    return font, lines


def draw_subtitle_on_image(
    image_path,
    text,
    output_path,
    font_path,
    font_size=55,
    rect_height=110,
    bottom_margin=50,
    rect_alpha=140,
    style="stroke",
    stroke_width=3,
    max_lines=2,
):
    """
    在图片底部绘制字幕。

    支持：
    - stroke：白字黑描边
    - banner：黑色半透明底条
    - 自动缩小字号
    - 自动换行
    - 超长文本省略号截断
    """

    img = Image.open(image_path)
    width, height = img.size

    # 根据图片的实际宽度与基准宽度 (1920) 自动等比缩放字幕尺寸参数，使字幕外观在不同分辨率下保持一致
    scale_factor = width / 1920.0
    font_size = max(12, int(font_size * scale_factor))
    rect_height = max(24, int(rect_height * scale_factor))
    bottom_margin = max(10, int(bottom_margin * scale_factor))
    stroke_width = max(1, int(stroke_width * scale_factor))
    min_font_size = max(6, int(28 * scale_factor))
    horizontal_margin = max(20, int(100 * scale_factor))

    if img.mode != "RGBA":
        img = img.convert("RGBA")

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font, lines = prepare_subtitle_lines(
        draw=draw,
        text=text,
        font_path=font_path,
        image_width=width,
        font_size=font_size,
        min_font_size=min_font_size,
        horizontal_margin=horizontal_margin,
        max_lines=max_lines,
        stroke_width=stroke_width if style == "stroke" else 0,
    )

    line_metrics = []
    total_text_height = 0

    line_gap = max(8, int(getattr(font, "size", font_size) * 0.18))

    for line in lines:
        bbox, line_width, line_height = measure_text(
            draw,
            line,
            font,
            stroke_width=stroke_width if style == "stroke" else 0,
        )
        line_metrics.append((line, bbox, line_width, line_height))
        total_text_height += line_height

    if len(lines) > 1:
        total_text_height += line_gap * (len(lines) - 1)

    if style == "banner":
        effective_rect_height = max(rect_height, total_text_height + 30)
        rect_y1 = height - bottom_margin - effective_rect_height
        rect_y2 = height - bottom_margin

        if rect_y1 < 0:
            rect_y1 = 0

        draw.rectangle([0, rect_y1, width, rect_y2], fill=(0, 0, 0, rect_alpha))

        start_y = rect_y1 + (effective_rect_height - total_text_height) // 2

        y = start_y

        for line, bbox, line_width, line_height in line_metrics:
            text_x = (width - line_width) // 2
            text_y = y - bbox[1]

            draw.text(
                (text_x, text_y),
                line,
                font=font,
                fill=(255, 255, 255, 255),
            )

            y += line_height + line_gap

    else:
        start_y = height - bottom_margin - total_text_height

        if start_y < 0:
            start_y = 0

        y = start_y

        for line, bbox, line_width, line_height in line_metrics:
            text_x = (width - line_width) // 2
            text_y = y - bbox[1]

            draw.text(
                (text_x, text_y),
                line,
                font=font,
                fill=(255, 255, 255, 255),
                stroke_width=stroke_width,
                stroke_fill=(0, 0, 0, 255),
            )

            y += line_height + line_gap

    final_img = Image.alpha_composite(img, overlay)
    final_img.convert("RGB").save(output_path, "PNG")


def get_sorted_images(directory, prefix="page"):
    """
    在目录下提取按数字排序的幻灯片图片列表。
    兼容：
    - page-1.png
    - page-02.png
    - page1.png
    - page001.jpg
    """

    pattern = re.compile(rf"^{re.escape(prefix)}-?(\d+)\.(png|jpg|jpeg)$", re.IGNORECASE)
    matches = []

    if os.path.exists(directory):
        for f in os.listdir(directory):
            m = pattern.match(f)
            if m:
                num = int(m.group(1))
                matches.append((num, os.path.join(directory, f)))

    matches.sort(key=lambda x: x[0])

    return [path for _, path in matches]


def convert_pdf_to_images(pdf_path, workdir, resolution=150):
    """
    调用系统 pdftoppm 工具将 PDF 幻灯片转为 PNG 图片。
    """

    if not os.path.exists(pdf_path):
        print(f"错误：PDF 文件不存在：{pdf_path}")
        sys.exit(1)

    prefix = os.path.join(workdir, "page")

    print(f"正在转换 PDF 幻灯片为图片：{pdf_path}")

    cmd = [
        "pdftoppm",
        "-png",
        "-r",
        str(resolution),
        pdf_path,
        prefix,
    ]

    try:
        subprocess.run(cmd, check=True)

    except FileNotFoundError:
        print("错误：未找到 pdftoppm 工具，请先安装 poppler。")
        print("macOS 可以执行：brew install poppler")
        print("Ubuntu/Debian 可以执行：sudo apt-get install poppler-utils")
        print("Windows 可安装 poppler，并将 bin 目录加入 PATH。")
        sys.exit(1)

    except subprocess.CalledProcessError as e:
        print(f"PDF 转换图片失败：{e}")
        sys.exit(1)


def parse_texts_file(texts_file):
    """
    解析幻灯片演讲文案文件。
    支持：
    1. 使用 --- 作为分页符
    2. 若无 ---，默认每个非空行对应一页幻灯片
    """

    if not os.path.exists(texts_file):
        print(f"错误：找不到文案文件：{texts_file}")
        sys.exit(1)

    with open(texts_file, "r", encoding="utf-8") as f:
        content = f.read()

    if "---" in content:
        slides = [slide.strip() for slide in content.split("---") if slide.strip()]
    else:
        slides = [line.strip() for line in content.splitlines() if line.strip()]

    return slides


def ffmpeg_concat_escape(path):
    """
    ffmpeg concat demuxer 路径转义。

    修复点：
    1. Windows 路径中的反斜杠 \ 会被 FFmpeg 当转义符，因此统一替换成 /
    2. 单引号需要转义
    3. 返回绝对路径，避免工作目录变化导致找不到文件
    """

    abs_path = os.path.abspath(path)

    # Windows 兼容关键：统一转为正斜杠
    abs_path = abs_path.replace("\\", "/")

    # 处理单引号
    abs_path = abs_path.replace("'", "'\\''")

    return abs_path


def build_video_filter_chain(fps, max_width=1920, max_height=1080):
    """
    构建 FFmpeg 视频滤镜链。

    功能：
    1. 使用 fps 滤镜重建 CFR 时间戳，降低音视频不同步风险
    2. 自动限制最大分辨率，避免 libx264 因超大图片报错
    3. 保持宽高比
    4. 确保输出宽高为偶数，避免 H.264 编码失败
    """

    max_width = int(max_width)
    max_height = int(max_height)

    # ratio = max(iw / max_width, ih / max_height)
    # ratio > 1 时等比缩小
    # ratio <= 1 时只修正偶数宽高
    scale_expr = (
        "scale="
        f"'if(gt(max(iw/{max_width},ih/{max_height}),1),"
        f"trunc(iw/max(iw/{max_width},ih/{max_height})/2)*2,"
        "trunc(iw/2)*2)'"
        ":"
        f"'if(gt(max(iw/{max_width},ih/{max_height}),1),"
        f"trunc(ih/max(iw/{max_width},ih/{max_height})/2)*2,"
        "trunc(ih/2)*2)'"
    )

    return f"fps={fps},{scale_expr}"


def run_subprocess_checked(cmd, error_message):
    """
    执行子进程命令，并在失败时打印 stdout/stderr。
    """

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="ignore")
        stdout_text = result.stdout.decode("utf-8", errors="ignore")

        print(error_message)

        if stdout_text.strip():
            print("----- stdout -----")
            print(stdout_text)

        if stderr_text.strip():
            print("----- stderr -----")
            print(stderr_text)

        sys.exit(1)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="PPT/PDF 幻灯片配音及高清字幕同步视频生成工具"
    )

    # 核心路径输入输出
    parser.add_argument("--pdf", help="输入的 PDF 幻灯片文件路径")
    parser.add_argument(
        "--pdf-dpi",
        type=int,
        default=360,
        help="PDF 转图片时的分辨率 (DPI)，默认 360 (适合 4K 输出)",
    )
    parser.add_argument(
        "--images-dir",
        help="输入的幻灯片图片目录。若已提取图片，可直接指定，与 --pdf 二选一",
    )
    parser.add_argument(
        "--texts-file",
        required=True,
        help="演讲文案文本文件路径，支持 --- 分页符或按行读取",
    )
    parser.add_argument("--output", required=True, help="输出的 MP4 视频路径")

    # 克隆器与配音参数
    parser.add_argument(
        "--cloner-dir",
        help="VoxCPM2 语音克隆器项目根路径，用于动态载入模型",
    )
    parser.add_argument(
        "--voice-ref",
        required=True,
        help="克隆所用参考配音 WAV 路径",
    )
    parser.add_argument(
        "--prompt-text",
        help="参考配音对应的逐字稿。可选，若未指定则从 --prompt-file 读取",
    )
    parser.add_argument(
        "--prompt-file",
        help="参考配音对应的逐字稿文件路径。可选",
    )

    # 视频/字幕自定义配置
    default_font = (
        r"C:\Windows\Fonts\msyh.ttc"
        if os.name == "nt"
        else "/System/Library/Fonts/STHeiti Medium.ttc"
    )

    parser.add_argument(
        "--font-path",
        default=default_font,
        help="绘制字幕的中文字体路径",
    )
    parser.add_argument(
        "--font-size",
        type=int,
        default=42,
        help="字幕基础字号，默认 42",
    )
    parser.add_argument(
        "--bottom-margin",
        type=int,
        default=15,
        help="字幕距离底部的距离，默认 15",
    )
    parser.add_argument(
        "--rect-height",
        type=int,
        default=85,
        help="字幕遮罩高度，默认 85，仅 style=banner 有效",
    )
    parser.add_argument(
        "--rect-alpha",
        type=int,
        default=140,
        help="字幕框半透明度 0-255，默认 140，仅 style=banner 有效",
    )
    parser.add_argument(
        "--subtitle-style",
        choices=["stroke", "banner"],
        default="banner",
        help="字幕样式：stroke 为描边白字；banner 为黑色半透明底条",
    )
    parser.add_argument(
        "--stroke-width",
        type=int,
        default=3,
        help="字幕描边宽度，默认 3",
    )
    parser.add_argument(
        "--subtitle-max-lines",
        type=int,
        default=2,
        help="字幕最大行数，默认 2",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=25,
        help="输出视频帧率，默认 25",
    )
    parser.add_argument(
        "--max-video-width",
        type=int,
        default=3840,
        help="输出视频最大宽度，默认 3840",
    )
    parser.add_argument(
        "--max-video-height",
        type=int,
        default=2160,
        help="输出视频最大高度，默认 2160",
    )

    # 运行控制参数
    parser.add_argument(
        "--workdir",
        default="./workdir_video",
        help="工作缓存目录，默认 ./workdir_video",
    )
    parser.add_argument(
        "--device",
        help="强制指定运行推理设备，例如 cuda、mps、cpu",
    )
    parser.add_argument(
        "--timesteps",
        type=int,
        default=50,
        help="音频合成推理步数，默认 50",
    )
    parser.add_argument(
        "--model-name",
        default="openbmb/VoxCPM2",
        help="模型载入名称，默认 openbmb/VoxCPM2",
    )
    parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="强制重建音频和字幕缓存，避免复用旧音频",
    )
    parser.add_argument(
        "--min-subtitle-units",
        type=int,
        default=8,
        help="字幕短句合并阈值，低于该长度会尝试与相邻句合并，默认 8",
    )
    parser.add_argument(
        "--max-subtitle-units",
        type=int,
        default=28,
        help="字幕合并后的最大长度，默认 28",
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="合成完成后不清理临时生成文件",
    )

    args = parser.parse_args()

    # 动态把 cloner 路径和虚拟环境 site-packages 写入 sys.path
    if args.cloner_dir:
        cloner_abs = os.path.abspath(args.cloner_dir)
        sys.path.append(cloner_abs)

        possible_sites = [
            os.path.join(cloner_abs, ".venv", "Lib", "site-packages"),
            os.path.join(cloner_abs, ".venv", "lib", "python3.12", "site-packages"),
            os.path.join(cloner_abs, ".venv", "lib", "python3.11", "site-packages"),
            os.path.join(cloner_abs, ".venv", "lib", "python3.10", "site-packages"),
            os.path.join(cloner_abs, ".venv", "lib", "python3.9", "site-packages"),
            os.path.join(cloner_abs, ".venv", "lib", "python3.8", "site-packages"),
        ]

        for site_path in possible_sites:
            if os.path.exists(site_path):
                sys.path.append(site_path)
                break

    # 输入校验
    if not args.pdf and not args.images_dir:
        print("错误：必须提供 --pdf 或 --images-dir 中的至少一项。")
        sys.exit(1)

    if args.pdf and args.images_dir:
        print("提示：同时提供了 --pdf 和 --images-dir，将优先使用 --pdf 转换得到的图片。")

    if args.images_dir and not os.path.exists(args.images_dir):
        print(f"错误：图片目录不存在：{args.images_dir}")
        sys.exit(1)

    if not os.path.exists(args.voice_ref):
        print(f"错误：参考音频不存在：{args.voice_ref}")
        sys.exit(1)

    if args.fps <= 0:
        print("错误：--fps 必须大于 0。")
        sys.exit(1)

    if args.max_video_width <= 0 or args.max_video_height <= 0:
        print("错误：--max-video-width 和 --max-video-height 必须大于 0。")
        sys.exit(1)

    if args.min_subtitle_units <= 0:
        print("错误：--min-subtitle-units 必须大于 0。")
        sys.exit(1)

    if args.max_subtitle_units < args.min_subtitle_units:
        print("错误：--max-subtitle-units 不能小于 --min-subtitle-units。")
        sys.exit(1)

    os.makedirs(args.workdir, exist_ok=True)

    temp_subs_dir = os.path.join(args.workdir, "temp_subs")
    audio_subs_dir = os.path.join(args.workdir, "audio_subs")

    if args.force_rebuild:
        if os.path.exists(temp_subs_dir):
            shutil.rmtree(temp_subs_dir, ignore_errors=True)

        if os.path.exists(audio_subs_dir):
            shutil.rmtree(audio_subs_dir, ignore_errors=True)

        print("已启用 --force-rebuild，旧的字幕图片和音频缓存已清理。")

    os.makedirs(temp_subs_dir, exist_ok=True)
    os.makedirs(audio_subs_dir, exist_ok=True)

    # 1. 获取幻灯片图片
    if args.pdf:
        convert_pdf_to_images(args.pdf, args.workdir, resolution=args.pdf_dpi)
        images_dir = args.workdir
    else:
        images_dir = args.images_dir

    slide_images = get_sorted_images(images_dir, prefix="page")

    if not slide_images:
        print(f"错误：在目录 {images_dir} 下找不到任何以 page 开头的幻灯片图片。")
        print("示例文件名：page-1.png、page-02.png、page001.jpg")
        sys.exit(1)

    print(f"检测到 {len(slide_images)} 张幻灯片图片")

    # 2. 解析演讲文案
    slide_texts = parse_texts_file(args.texts_file)
    print(f"解析到 {len(slide_texts)} 页演讲文案")

    if not slide_texts:
        print("错误：演讲文案为空。")
        sys.exit(1)

    # 文案与图片数量校验
    if len(slide_texts) != len(slide_images):
        print(f"警告：文案页数 ({len(slide_texts)}) 与幻灯片图片数量 ({len(slide_images)}) 不匹配。")

        min_pages = min(len(slide_texts), len(slide_images))

        if min_pages <= 0:
            print("错误：没有可处理的幻灯片或文案。")
            sys.exit(1)

        slide_texts = slide_texts[:min_pages]
        slide_images = slide_images[:min_pages]

        print(f"程序将仅处理前 {min_pages} 页。")

    # 3. 载入参考音频逐字稿
    ref_voice_text = ""

    if args.prompt_file:
        if os.path.exists(args.prompt_file):
            with open(args.prompt_file, "r", encoding="utf-8") as f:
                ref_voice_text = f.read().strip()
        else:
            print(f"警告：未找到参考文本文件：{args.prompt_file}，将尝试使用 --prompt-text。")

    if not ref_voice_text and args.prompt_text:
        ref_voice_text = args.prompt_text.strip()

    if not ref_voice_text:
        print("错误：必须通过 --prompt-file 或 --prompt-text 提供参考音频的逐字稿。")
        sys.exit(1)

    # 4. 载入模型
    print("正在初始化语音克隆模型与加载依赖...")

    device = args.device or detect_device()
    print(f"当前推理设备：{device}")

    try:
        from voxcpm import VoxCPM
        import soundfile as sf
        import numpy as np

    except ImportError as e:
        print(f"导入依赖失败：{e}")
        print("请确保已安装 requirements.txt 依赖，或指定正确的 --cloner-dir。")
        print("也可以在 VoxCPM2 的虚拟环境中运行本脚本。")
        sys.exit(1)

    t0 = time.time()

    try:
        model = VoxCPM.from_pretrained(
            args.model_name,
            load_denoiser=False,
            device=device,
            optimize=False,
        )
    except Exception as e:
        print(f"语音克隆模型载入失败：{e}")
        sys.exit(1)

    print(f"语音克隆模型载入成功，耗时 {time.time() - t0:.1f}s")

    global_image_list = []
    global_audio_list = []

    # 5. 循环处理每页幻灯片和文案
    for idx, paragraph_text in enumerate(slide_texts):
        slide_num = idx + 1
        image_path = slide_images[idx]

        print(f"\n--- 正在处理幻灯片第 {slide_num} 页 / 共 {len(slide_texts)} 页 ---")
        print(f"图片路径：{image_path}")

        sentences = split_text_to_sentences(paragraph_text)

        sentences = merge_too_short_sentences(
            sentences,
            min_units=args.min_subtitle_units,
            max_units=args.max_subtitle_units,
        )

        if not sentences:
            print("警告：当前页文案未切分出有效字幕句子，跳过该页。")
            continue

        print(f"切分并合并后得到 {len(sentences)} 个字幕短句：")

        for s_idx, sentence in enumerate(sentences):
            sentence = sentence.strip()

            if not sentence:
                continue

            tts_text = normalize_text_for_tts(sentence)

            audio_name = build_audio_cache_name(
                slide_num=slide_num,
                sentence_idx=s_idx,
                sentence=sentence,
                tts_text=tts_text,
                args=args,
                ref_voice_text=ref_voice_text,
            )

            image_sub_name = f"slide_{slide_num:02d}_sub_{s_idx:02d}.png"

            audio_path = os.path.join(audio_subs_dir, audio_name)
            image_sub_path = os.path.join(temp_subs_dir, image_sub_name)

            # 5.1 生成配音，支持 hash 缓存
            if not os.path.exists(audio_path):
                print(f"  正在生成配音：{sentence}")
                print(f"  TTS 规范化文本：{tts_text}")

                if tts_text.strip():
                    try:
                        wav = model.generate(
                            text=tts_text,
                            prompt_wav_path=args.voice_ref,
                            prompt_text=ref_voice_text,
                            reference_wav_path=args.voice_ref,
                            cfg_value=2.0,
                            inference_timesteps=args.timesteps,
                        )
                        # 优化：在音频尾部拼接一小段静音 (0.25 秒)，提供自然的换气与停顿，避免句子拼接太紧密
                        sample_rate = getattr(model.tts_model, "sample_rate", 24000)
                        silence_len = int(sample_rate * 0.25)
                        silence = np.zeros(silence_len, dtype=np.float32)
                        wav = np.concatenate([wav, silence])
                    except Exception as e:
                        print(f"生成配音失败：{e}")
                        sys.exit(1)
                else:
                    sample_rate = getattr(model.tts_model, "sample_rate", 24000)
                    wav = np.zeros(int(sample_rate * 0.5), dtype=np.float32)

                sample_rate = getattr(model.tts_model, "sample_rate", 24000)

                try:
                    sf.write(audio_path, wav, sample_rate)
                except Exception as e:
                    print(f"写入音频失败：{audio_path}")
                    print(e)
                    sys.exit(1)

            else:
                print(f"  使用配音缓存：{audio_name}")

            # 5.2 获取音频物理时长
            try:
                wav_data, sr = sf.read(audio_path)
                duration = wav_data.shape[0] / sr
            except Exception as e:
                print(f"读取音频时长失败：{audio_path}")
                print(e)
                sys.exit(1)

            if duration <= 0:
                print(f"警告：音频时长异常，使用 0.5 秒兜底：{audio_path}")
                duration = 0.5

            print(f"  - 物理时长：{duration:.2f}s | {sentence}")

            # 5.3 绘制字幕图片
            try:
                draw_subtitle_on_image(
                    image_path=image_path,
                    text=sentence,
                    output_path=image_sub_path,
                    font_path=args.font_path,
                    font_size=args.font_size,
                    rect_height=args.rect_height,
                    bottom_margin=args.bottom_margin,
                    rect_alpha=args.rect_alpha,
                    style=args.subtitle_style,
                    stroke_width=args.stroke_width,
                    max_lines=args.subtitle_max_lines,
                )
            except Exception as e:
                print(f"绘制字幕图片失败：{image_sub_path}")
                print(e)
                sys.exit(1)

            global_image_list.append((image_sub_path, duration))
            global_audio_list.append(audio_path)

    print("\n--- 音视频全局混流合并开始 ---")

    if not global_image_list or not global_audio_list:
        print("错误：没有生成任何字幕图片或音频，请检查文案内容和幻灯片数量。")
        sys.exit(1)

    # 6. 生成全局无声视频 concat 列表
    concat_v_file = os.path.join(args.workdir, "concat_videos_silent.txt")

    with open(concat_v_file, "w", encoding="utf-8") as f:
        for path, d in global_image_list:
            f.write(f"file '{ffmpeg_concat_escape(path)}'\n")
            f.write(f"duration {d:.6f}\n")

        # FFmpeg concat 需要末尾重复最后一张图片，以确定最后一段 duration
        f.write(f"file '{ffmpeg_concat_escape(global_image_list[-1][0])}'\n")

    final_silent_mp4 = os.path.join(args.workdir, "final_silent.mp4")

    print("正在使用 ffmpeg 一次性合成大无声视频...")

    t_v = time.time()

    vf_chain = build_video_filter_chain(
        fps=args.fps,
        max_width=args.max_video_width,
        max_height=args.max_video_height,
    )

    print(f"视频滤镜链：{vf_chain}")

    cmd_v = [
        "ffmpeg",
        "-y",
        "-fflags",
        "+genpts",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_v_file,
        "-vf",
        vf_chain,
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "superfast",
        "-tune",
        "stillimage",
        "-crf",
        "18",
        "-movflags",
        "+faststart",
        final_silent_mp4,
    ]

    run_subprocess_checked(cmd_v, "大无声视频拼接失败：")

    print(f"大无声视频拼接完成 -> {final_silent_mp4}，耗时 {time.time() - t_v:.1f}s")

    # 7. 生成全局大音频 concat 列表
    concat_a_file = os.path.join(args.workdir, "concat_audios.txt")

    with open(concat_a_file, "w", encoding="utf-8") as f:
        for a in global_audio_list:
            f.write(f"file '{ffmpeg_concat_escape(a)}'\n")

    final_audio_wav = os.path.join(args.workdir, "final_audio.wav")

    print("正在使用 ffmpeg 一次性拼接全局大音轨...")

    # 不使用 -c copy，改为重新编码 PCM，兼容性更稳
    cmd_a = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_a_file,
        "-acodec",
        "pcm_s16le",
        final_audio_wav,
    ]

    run_subprocess_checked(cmd_a, "大音轨拼接失败：")

    print(f"大音轨拼接完成 -> {final_audio_wav}")

    # 8. 最终音视频混流
    print(f"正在进行最终音视频全局混流输出到：{args.output}")

    t_mix = time.time()

    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)

    cmd_mix = [
        "ffmpeg",
        "-y",
        "-i",
        final_silent_mp4,
        "-i",
        final_audio_wav,
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-shortest",
        "-movflags",
        "+faststart",
        args.output,
    ]

    run_subprocess_checked(cmd_mix, "音视频混流失败：")

    # 清理临时字幕图片
    if not args.no_cleanup:
        try:
            shutil.rmtree(temp_subs_dir)
            print("已清理临时字幕图片目录")
        except Exception as e:
            print(f"警告：清理临时字幕图片目录失败：{e}")

    print(f"最终完整视频合成完毕，混流耗时 {time.time() - t_mix:.1f}s")
    print(f"输出文件路径：{os.path.abspath(args.output)}")
    print("所有生成步骤已顺利执行完毕！")


if __name__ == "__main__":
    main()