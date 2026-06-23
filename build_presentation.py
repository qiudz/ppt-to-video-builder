#!/usr/bin/env python3
import os
import sys
import subprocess
import time
import re
import shutil
import argparse
from PIL import Image, ImageDraw, ImageFont

def detect_device():
    """自动检测硬件加速设备"""
    try:
        import torch
        if torch.cuda.is_available():
            return 'cuda'
        if hasattr(torch, 'xpu') and torch.xpu.is_available():
            return 'xpu'
        if torch.backends.mps.is_available():
            return 'mps'
    except ImportError:
        pass
    return 'cpu'

def split_text_to_sentences(text, max_len=20, min_len=10):
    """
    智能将段落文案切分成有意义的字幕短句，排除任何单独成句的标点符号。
    """
    raw_sentences = re.findall(r'[^，。？！；、,.?!;]+[，。？！；、,.?!;]*', text)
    
    sentences = []
    current = ""
    for s in raw_sentences:
        if not re.search(r'[\u4e00-\u9fa5a-zA-Z0-9]', s):
            if sentences:
                sentences[-1] += s
            elif current:
                current += s
            continue
            
        current += s
        char_count = len(re.findall(r'[\u4e00-\u9fa5]|[a-zA-Z0-9]+', current))
        if char_count >= min_len:
            sentences.append(current.strip())
            current = ""
            
    if current:
        if sentences:
            sentences[-1] += current
        else:
            sentences.append(current)
            
    final_sentences = []
    for s in sentences:
        char_count = len(re.findall(r'[\u4e00-\u9fa5]|[a-zA-Z0-9]+', s))
        if char_count > max_len:
            subparts = re.findall(r'[^，、, ]+[，、, ]*', s)
            sub_current = ""
            for sp in subparts:
                sub_current += sp
                sub_char = len(re.findall(r'[\u4e00-\u9fa5]|[a-zA-Z0-9]+', sub_current))
                if sub_char >= min_len:
                    final_sentences.append(sub_current.strip())
                    sub_current = ""
            if sub_current:
                if final_sentences:
                    final_sentences[-1] += sub_current
                else:
                    final_sentences.append(sub_current)
        else:
            final_sentences.append(s)
            
    cleaned = []
    for s in final_sentences:
        s = s.strip()
        if re.search(r'[\u4e00-\u9fa5a-zA-Z0-9]', s):
            cleaned.append(s)
        else:
            if cleaned:
                cleaned[-1] += s
    return cleaned

def draw_subtitle_on_image(image_path, text, output_path, font_path, font_size=55, rect_height=90, bottom_margin=50, rect_alpha=140, style="stroke", stroke_width=3):
    """
    在图片底部绘制字幕。
    - font_path: 字体路径，macOS 默认华文黑体 STHeiti Medium
    - font_size: 字幕基础大小
    - rect_height: 黑色半透明底条的高度 (只在 style="banner" 时有效)
    - bottom_margin: 字幕距离最底部的边距
    - rect_alpha: 底条的半透明度 (0-255) (只在 style="banner" 时有效)
    - style: 字幕类型，"stroke" (白色文字+黑色描边) 或 "banner" (半透明底条)
    - stroke_width: 描边像素宽度 (只在 style="stroke" 时有效)
    """
    img = Image.open(image_path)
    width, height = img.size
    
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
        
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    font = None
    current_size = font_size
    
    while current_size >= 24:
        try:
            font = ImageFont.truetype(font_path, current_size)
        except IOError:
            # 备用方案使用系统默认字体（但中文字体通常需要 TrueType）
            font = ImageFont.load_default()
            break
            
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        # 预留安全边距，左右各预留 100 像素，总宽度不能越界
        if text_width <= width - 200:
            break
        current_size -= 2
        
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    if style == "banner":
        rect_y1 = height - bottom_margin - rect_height
        rect_y2 = height - bottom_margin
        
        # 绘制半透明黑底字幕遮罩
        draw.rectangle([0, rect_y1, width, rect_y2], fill=(0, 0, 0, rect_alpha))
        
        # 计算文字的绝对居中坐标
        text_x = (width - text_width) // 2
        text_y = rect_y1 + (rect_height - text_height) // 2 - bbox[1]
        
        draw.text((text_x, text_y), text, font=font, fill=(255, 255, 255, 255))
    else: # stroke 描边样式
        # 居中水平坐标，垂直坐标根据 bottom_margin 贴底
        text_x = (width - text_width) // 2
        text_y = height - bottom_margin - text_height - bbox[1]
        
        # 绘制白字加黑描边
        draw.text(
            (text_x, text_y), 
            text, 
            font=font, 
            fill=(255, 255, 255, 255), 
            stroke_width=stroke_width, 
            stroke_fill=(0, 0, 0, 255)
        )
    
    final_img = Image.alpha_composite(img, overlay)
    final_img.convert('RGB').save(output_path, 'PNG')

def get_sorted_images(directory, prefix="page"):
    """
    在目录下提取按数字排序的幻灯片图片列表。
    能兼容 page-1.png, page-02.png 等不同格式。
    """
    pattern = re.compile(rf"^{prefix}-?(\d+)\.(png|jpg|jpeg)$", re.IGNORECASE)
    matches = []
    if os.path.exists(directory):
        for f in os.listdir(directory):
            m = pattern.match(f)
            if m:
                num = int(m.group(1))
                matches.append((num, os.path.join(directory, f)))
    matches.sort(key=lambda x: x[0])
    return [path for num, path in matches]

def convert_pdf_to_images(pdf_path, workdir, resolution=150):
    """
    调用系统 pdftoppm 工具将 PDF 幻灯片转为 PNG 图片。
    """
    prefix = os.path.join(workdir, "page")
    print(f"正在转换 PDF 幻灯片为图片: {pdf_path}")
    cmd = [
        "pdftoppm", "-png",
        "-r", str(resolution),
        pdf_path, prefix
    ]
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        print("错误：未找到 pdftoppm 工具，请先在系统中安装 poppler。")
        print("macOS 可以通过命令安装: brew install poppler")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"PDF 转换图片失败: {e}")
        sys.exit(1)

def parse_texts_file(texts_file):
    """
    解析幻灯片演讲文案文件。
    支持以 '---' 作为分页符，若无 '---'，则默认每行文字（非空）对应一页幻灯片。
    """
    if not os.path.exists(texts_file):
        print(f"错误：找不到文案文件 {texts_file}")
        sys.exit(1)
        
    with open(texts_file, 'r', encoding='utf-8') as f:
        content = f.read()
        
    if "---" in content:
        # 使用分页符分割，过滤前后空格
        slides = [slide.strip() for slide in content.split("---") if slide.strip()]
    else:
        # 按行分割，过滤空行
        slides = [line.strip() for line in content.splitlines() if line.strip()]
        
    return slides

def main():
    parser = argparse.ArgumentParser(description="PPT/PDF 幻灯片配音及高清字幕同步视频生成工具")
    
    # 核心路径输入输出
    parser.add_argument("--pdf", help="输入的 PDF 幻灯片文件路径")
    parser.add_argument("--images-dir", help="输入的幻灯片图片目录（若已提取图片，可直接指定，与 --pdf 二选一）")
    parser.add_argument("--texts-file", required=True, help="演讲文案文本文件路径（支持 '---' 分页符或按行读取）")
    parser.add_argument("--output", required=True, help="输出的 MP4 视频路径")
    
    # 克隆器与配音参数
    parser.add_argument("--cloner-dir", help="VoxCPM2 语音克隆器项目的根路径（用于动态载入模型）")
    parser.add_argument("--voice-ref", required=True, help="克隆所用参考配音的 WAV 路径")
    parser.add_argument("--prompt-text", help="参考配音对应的逐字稿（字符串，可选）")
    parser.add_argument("--prompt-file", help="参考配音对应的逐字稿文件路径（可选，若未指定则从 --prompt-text 读取）")
    
    # 视频/字幕自定义配置
    default_font = "C:\\Windows\\Fonts\\msyh.ttc" if os.name == 'nt' else "/System/Library/Fonts/STHeiti Medium.ttc"
    parser.add_argument("--font-path", default=default_font, help="绘制字幕的中文字体路径")
    parser.add_argument("--font-size", type=int, default=55, help="字幕基础字号 (默认 55)")
    parser.add_argument("--bottom-margin", type=int, default=50, help="字幕距离底部的距离 (默认 50)")
    parser.add_argument("--rect-height", type=int, default=90, help="字幕遮罩高度 (默认 90，仅在 style 为 banner 时有效)")
    parser.add_argument("--rect-alpha", type=int, default=140, help="字幕框半透明度 0-255 (默认 140，仅在 style 为 banner 时有效)")
    parser.add_argument("--subtitle-style", choices=["stroke", "banner"], default="stroke", help="字幕渲染样式：stroke(描边白字，默认)，banner(黑色半透明底条)")
    parser.add_argument("--stroke-width", type=int, default=3, help="字幕描边宽度 (默认 3)")
    
    # 运行控制参数
    parser.add_argument("--workdir", default="./workdir_video", help="工作缓存目录（默认 ./workdir_video）")
    parser.add_argument("--device", help="强制指定运行推理设备 (cuda/mps/cpu 等)")
    parser.add_argument("--timesteps", type=int, default=50, help="音频合成推理步数 (默认 50)")
    parser.add_argument("--model-name", default="openbmb/VoxCPM2", help="模型载入名称 (默认 openbmb/VoxCPM2)")
    parser.add_argument("--no-cleanup", action="store_true", help="合成完成后不清理临时生成文件")
    
    args = parser.parse_args()
    
    # 动态把 cloner 路径和它的 site-packages 写入 path，以便在没有安装全局依赖时运行
    if args.cloner_dir:
        cloner_abs = os.path.abspath(args.cloner_dir)
        sys.path.append(cloner_abs)
        # 兼容虚拟环境
        venv_site = os.path.join(cloner_abs, ".venv", "lib", "python3.10", "site-packages")
        if not os.path.exists(venv_site):
            # 尝试 Windows 的 Lib/site-packages
            windows_site = os.path.join(cloner_abs, ".venv", "Lib", "site-packages")
            if os.path.exists(windows_site):
                venv_site = windows_site
            else:
                # 尝试 3.9 或 3.8 或 3.11 等常见目录
                for py_ver in ["python3.9", "python3.11", "python3.8", "python3.12"]:
                    candidate = os.path.join(cloner_abs, ".venv", "lib", py_ver, "site-packages")
                    if os.path.exists(candidate):
                        venv_site = candidate
                        break
        if os.path.exists(venv_site):
            sys.path.append(venv_site)
            
    # 校验输入
    if not args.pdf and not args.images_dir:
        print("错误：必须提供 --pdf 或 --images-dir 中的至少一项！")
        sys.exit(1)
        
    os.makedirs(args.workdir, exist_ok=True)
    temp_subs_dir = os.path.join(args.workdir, "temp_subs")
    audio_subs_dir = os.path.join(args.workdir, "audio_subs")
    os.makedirs(temp_subs_dir, exist_ok=True)
    os.makedirs(audio_subs_dir, exist_ok=True)
    
    # 1. 确保获取幻灯片图片目录
    if args.pdf:
        convert_pdf_to_images(args.pdf, args.workdir)
        images_dir = args.workdir
    else:
        images_dir = args.images_dir
        
    # 获取按顺序排列的图片文件列表
    slide_images = get_sorted_images(images_dir, prefix="page")
    if not slide_images:
        print(f"错误：在目录 {images_dir} 下找不到任何以 page 开头的幻灯片图片。")
        sys.exit(1)
        
    # 2. 解析演讲文案
    slide_texts = parse_texts_file(args.texts_file)
    print(f"解析到 {len(slide_texts)} 页演讲文案")
    
    # 校验文案与幻灯片图片数量
    if len(slide_texts) != len(slide_images):
        print(f"警告：文案页数 ({len(slide_texts)}) 与幻灯片图片数量 ({len(slide_images)}) 不匹配！")
        # 截断以最小值为准
        min_pages = min(len(slide_texts), len(slide_images))
        slide_texts = slide_texts[:min_pages]
        slide_images = slide_images[:min_pages]
        print(f"程序将仅处理前 {min_pages} 页。")
        
    # 3. 载入克隆器参考音文字
    ref_voice_text = ""
    if args.prompt_file:
        if os.path.exists(args.prompt_file):
            with open(args.prompt_file, 'r', encoding='utf-8') as f:
                ref_voice_text = f.read().strip()
        else:
            print(f"警告：未找到参考文本文件 {args.prompt_file}，将尝试使用 --prompt-text 参数。")
            
    if not ref_voice_text and args.prompt_text:
        ref_voice_text = args.prompt_text
        
    if not ref_voice_text:
        print("错误：必须通过 --prompt-file 或 --prompt-text 提供参考音频的逐字稿内容！")
        sys.exit(1)
        
    # 4. 载入克隆模型
    print("正在初始化语音克隆模型与加载依赖...")
    device = args.device or detect_device()
    try:
        from voxcpm import VoxCPM
        import soundfile as sf
    except ImportError as e:
        print(f"导入依赖失败: {e}")
        print("请确保已安装 requirements.txt 依赖，或指定正确的 --cloner-dir 且在其虚拟环境中运行此脚本。")
        sys.exit(1)
        
    t0 = time.time()
    model = VoxCPM.from_pretrained(
        args.model_name,
        load_denoiser=False,
        device=device,
        optimize=False
    )
    print(f"语音克隆模型载入成功，耗时 {time.time()-t0:.1f}s")
    
    global_image_list = []
    global_audio_list = []
    
    # 5. 循环处理每页 PPT 和文案
    for idx, paragraph_text in enumerate(slide_texts):
        slide_num = idx + 1
        image_path = slide_images[idx]
        print(f"\n--- 正在处理幻灯片第 {slide_num} 页 / 共 {len(slide_texts)} 页 ---")
        print(f"图片路径: {image_path}")
        
        # 分句
        sentences = split_text_to_sentences(paragraph_text)
        print(f"切分出 {len(sentences)} 个字幕短句:")
        
        for s_idx, sentence in enumerate(sentences):
            audio_name = f"audio_{slide_num:02d}_{s_idx:02d}.wav"
            image_sub_name = f"slide_{slide_num:02d}_sub_{s_idx:02d}.png"
            
            audio_path = os.path.join(audio_subs_dir, audio_name)
            image_sub_path = os.path.join(temp_subs_dir, image_sub_name)
            
            # 5.1 生成配音 (缓存检查)
            if not os.path.exists(audio_path):
                print(f"  正在生成配音: {sentence}")
                wav = model.generate(
                    text=sentence,
                    prompt_wav_path=args.voice_ref,
                    prompt_text=ref_voice_text,
                    reference_wav_path=args.voice_ref,
                    cfg_value=2.0,
                    inference_timesteps=args.timesteps
                )
                sf.write(audio_path, wav, model.tts_model.sample_rate)
            else:
                print(f"  使用配音缓存: {audio_name}")
                
            # 5.2 获取物理时长
            wav_data, sr = sf.read(audio_path)
            duration = len(wav_data) / sr
            print(f"  - 物理时长: {duration:.2f}s | {sentence}")
            
            # 5.3 绘制字幕底条
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
                stroke_width=args.stroke_width
            )
            
            global_image_list.append((image_sub_path, duration))
            global_audio_list.append(audio_path)
            
    print("\n--- 音视频全局混流合并开始 ---")
    
    # 6. 生成全局大无声视频的 concat 列表
    concat_v_file = os.path.join(args.workdir, "concat_videos_silent.txt")
    with open(concat_v_file, 'w', encoding='utf-8') as f:
        for path, d in global_image_list:
            f.write(f"file '{os.path.abspath(path)}'\n")
            f.write(f"duration {d:.6f}\n")
        # ffmpeg concat 必须在末尾重复最后一张图片以确定时长
        f.write(f"file '{os.path.abspath(global_image_list[-1][0])}'\n")
        
    final_silent_mp4 = os.path.join(args.workdir, "final_silent.mp4")
    print("正在使用 ffmpeg 一次性合成大无声视频...")
    t_v = time.time()
    cmd_v = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_v_file,
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt", "yuv420p",
        "-r", "25",
        "-c:v", "libx264",
        final_silent_mp4
    ]
    subprocess.run(cmd_v, check=True)
    print(f"大无声视频拼接完成 -> {final_silent_mp4}，耗时 {time.time()-t_v:.1f}s")
    
    # 7. 生成全局大音频的 concat 列表
    concat_a_file = os.path.join(args.workdir, "concat_audios.txt")
    with open(concat_a_file, 'w', encoding='utf-8') as f:
        for a in global_audio_list:
            f.write(f"file '{os.path.abspath(a)}'\n")
            
    final_audio_wav = os.path.join(args.workdir, "final_audio.wav")
    print("正在使用 ffmpeg 一次性拼接全局大音轨...")
    cmd_a = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_a_file,
        "-c", "copy",
        final_audio_wav
    ]
    subprocess.run(cmd_a, check=True)
    print(f"大音轨拼接完成 -> {final_audio_wav}")
    
    # 8. 最终音视频全局混流
    print(f"正在进行最终音视频全局混流输出到: {args.output}")
    t_mix = time.time()
    # 确保输出目录存在
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    
    cmd_mix = [
        "ffmpeg", "-y",
        "-i", final_silent_mp4,
        "-i", final_audio_wav,
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        args.output
    ]
    result_mix = subprocess.run(cmd_mix, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result_mix.returncode != 0:
        print(f"音视频混流失败: {result_mix.stderr.decode('utf-8')}")
        sys.exit(1)
        
    # 清理临时渲染出的带有字幕的 PNG 图片
    if not args.no_cleanup:
        try:
            shutil.rmtree(temp_subs_dir)
            print("已清理临时字幕图片目录")
        except Exception:
            pass
            
    print(f"最终完整视频合成完毕，混流耗时 {time.time()-t_mix:.1f}s")
    print(f"输出文件路径: {os.path.abspath(args.output)}")
    print("所有生成步骤已顺利执行完毕！")

if __name__ == "__main__":
    main()
