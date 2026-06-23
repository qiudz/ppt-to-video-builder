#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import time
import re
import shutil
import argparse
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

        char_count = len(re.findall(r"[\u4e00-\u9fa5]|[a-zA-Z0-9]+", current))
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
        char_count = len(re.findall(r"[\u4e00-\u9fa5]|[a-zA-Z0-9]+", s))

        if char_count > max_len:
            subparts = re.findall(r"[^，、, ]+[，、, ]*", s)
            sub_current = ""

            for sp in subparts:
                sub_current += sp
                sub_char = len(re.findall(r"[\u4e00-\u9fa5]|[a-zA-Z0-9]+", sub_current))

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

    # 1. 删除 $$...$$ 动作提示，例如：$$讲师操作演示环节$$
    text = re.sub(r"\$\$.*?\$\$", " ", text, flags=re.S)

    # 2. 删除 Markdown 代码块，保留行内代码内容
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)

    # 3. 常见技术词、产品名、缩写、文件名特殊处理
    # 注意：这些会在路径和后缀处理之前执行
    replacements = {
        r"\bCLAUDE\.md\b": "Claude MD",
        r"\bClaude\.md\b": "Claude MD",
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

    # 4. 常见命令优先处理，避免后续符号清洗破坏含义
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
    # /help -> 斜杠 help
    text = re.sub(r"(?<!\w)/([a-zA-Z0-9_\-]+)", r" 斜杠 \1 ", text)

    # 6. 处理命令参数
    # --help -> 参数 help
    # -v -> 参数 v
    text = re.sub(r"--([a-zA-Z0-9_\-]+)", r" 参数 \1 ", text)
    text = re.sub(r"(?<!\w)-([a-zA-Z])\b", r" 参数 \1 ", text)

    # 7. 处理 @引用
    # @docs/api.md -> docs api MD
    text = text.replace("@", " ")

    # 8. 处理路径分隔符
    # src/app/page.tsx -> src app page TSX
    text = text.replace("\\", " 反斜杠 ")
    text = re.sub(r"[/]+", " ", text)

    # 9. 文件后缀统一处理
    # 注意：长后缀必须先处理，避免 .tsx 被 .ts 提前替换
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

    # 11. 处理下划线、等号、加号、百分号等
    text = text.replace("_", " ")
    text = text.replace("=", " 等于 ")
    text = text.replace("+", " 加 ")
    text = text.replace("&", " 和 ")
    text = text.replace("%", " 百分号 ")

    # 12. 清理容易导致 TTS 异常的符号
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

    # 13. 清理中英文引号
    text = (
        text.replace("‘", "")
        .replace("’", "")
        .replace("“", "")
        .replace("”", "")
        .replace('"', "")
        .replace("'", "")
    )

    # 14. 连续破折号、减号处理
    text = re.sub(r"[-—–]+", " ", text)

    # 15. 标点规范化
    # 保留中文自然停顿
    text = re.sub(r"[;,]+", "，", text)
    text = re.sub(r"[.]+", "。", text)
    text = re.sub(r"[:：]{2,}", "：", text)

    # 16. 合并空格
    text = re.sub(r"\s+", " ", text)

    # 17. 清理重复中文标点
    text = re.sub(r"，+", "，", text)
    text = re.sub(r"。+", "。", text)
    text = re.sub(r"！+", "！", text)
    text = re.sub(r"？+", "？", text)

    return text.strip()


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
        ])

    for fp in candidate_fonts:
        if fp and os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, font_size)
            except Exception:
                continue

    return ImageFont.load_default()


def draw_subtitle_on_image(
    image_path,
    text,
    output_path,
    font_path,
    font_size=55,
    rect_height=90,
    bottom_margin=50,
    rect_alpha=140,
    style="stroke",
    stroke_width=3,
):
    """
    在图片底部绘制字幕。

    参数：
    - font_path: 字体路径
    - font_size: 字幕基础大小
    - rect_height: 半透明底条高度，仅 style="banner" 生效
    - bottom_margin: 字幕距离底部距离
    - rect_alpha: 底条透明度，仅 style="banner" 生效
    - style: stroke 白字黑描边；banner 黑色半透明底条
    - stroke_width: 描边宽度
    """

    img = Image.open(image_path)
    width, height = img.size

    if img.mode != "RGBA":
        img = img.convert("RGBA")

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    current_size = font_size
    font = None

    while current_size >= 24:
        font = load_font_safely(font_path, current_size)

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]

        # 左右各预留 100 像素
        if text_width <= width - 200:
            break

        current_size -= 2

    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    if style == "banner":
        rect_y1 = height - bottom_margin - rect_height
        rect_y2 = height - bottom_margin

        draw.rectangle([0, rect_y1, width, rect_y2], fill=(0, 0, 0, rect_alpha))

        text_x = (width - text_width) // 2
        text_y = rect_y1 + (rect_height - text_height) // 2 - bbox[1]

        draw.text(
            (text_x, text_y),
            text,
            font=font,
            fill=(255, 255, 255, 255),
        )

    else:
        text_x = (width - text_width) // 2
        text_y = height - bottom_margin - text_height - bbox[1]

        draw.text(
            (text_x, text_y),
            text,
            font=font,
            fill=(255, 255, 255, 255),
            stroke_width=stroke_width,
            stroke_fill=(0, 0, 0, 255),
        )

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

    print(f"正在转换 PDF 幻灯片为图片: {pdf_path}")

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
        print(f"PDF 转换图片失败: {e}")
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
    ffmpeg concat demuxer 的单引号路径转义。
    """

    abs_path = os.path.abspath(path)
    return abs_path.replace("'", "'\\''")


def run_subprocess_checked(cmd, error_message):
    """
    执行子进程命令，并在失败时打印 stderr。
    """

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="ignore")
        print(error_message)
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
        default=55,
        help="字幕基础字号，默认 55",
    )
    parser.add_argument(
        "--bottom-margin",
        type=int,
        default=50,
        help="字幕距离底部的距离，默认 50",
    )
    parser.add_argument(
        "--rect-height",
        type=int,
        default=90,
        help="字幕遮罩高度，默认 90，仅 style=banner 有效",
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
        default="stroke",
        help="字幕样式：stroke 为描边白字；banner 为黑色半透明底条",
    )
    parser.add_argument(
        "--stroke-width",
        type=int,
        default=3,
        help="字幕描边宽度，默认 3",
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

    os.makedirs(args.workdir, exist_ok=True)

    temp_subs_dir = os.path.join(args.workdir, "temp_subs")
    audio_subs_dir = os.path.join(args.workdir, "audio_subs")

    os.makedirs(temp_subs_dir, exist_ok=True)
    os.makedirs(audio_subs_dir, exist_ok=True)

    # 1. 获取幻灯片图片
    if args.pdf:
        convert_pdf_to_images(args.pdf, args.workdir)
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

        if not sentences:
            print("警告：当前页文案未切分出有效字幕句子，跳过该页。")
            continue

        print(f"切分出 {len(sentences)} 个字幕短句：")

        for s_idx, sentence in enumerate(sentences):
            sentence = sentence.strip()

            if not sentence:
                continue

            audio_name = f"audio_{slide_num:02d}_{s_idx:02d}.wav"
            image_sub_name = f"slide_{slide_num:02d}_sub_{s_idx:02d}.png"

            audio_path = os.path.join(audio_subs_dir, audio_name)
            image_sub_path = os.path.join(temp_subs_dir, image_sub_name)

            # 5.1 生成配音，支持缓存
            if not os.path.exists(audio_path):
                tts_text = normalize_text_for_tts(sentence)

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
                    except Exception as e:
                        print(f"生成配音失败：{e}")
                        sys.exit(1)
                else:
                    # 如果规范化后为空，则生成 0.5 秒静音
                    sample_rate = getattr(model.tts_model, "sample_rate", 24000)
                    wav = np.zeros(int(sample_rate * 0.5), dtype=np.float32)

                sample_rate = getattr(model.tts_model, "sample_rate", 24000)
                sf.write(audio_path, wav, sample_rate)

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

        # ffmpeg concat 需要末尾重复最后一张图片以确定最后一段时长
        f.write(f"file '{ffmpeg_concat_escape(global_image_list[-1][0])}'\n")

    final_silent_mp4 = os.path.join(args.workdir, "final_silent.mp4")

    print("正在使用 ffmpeg 一次性合成大无声视频...")

    t_v = time.time()

    cmd_v = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_v_file,
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "25",
        "-c:v",
        "libx264",
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
        "-shortest",
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