# -*- coding: utf-8 -*-
"""文字生视频端到端测试 — 绕过 GUI 直接用引擎跑完整管线"""
import os, sys, json, time, threading

# 确保项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QCoreApplication
from videotrans.text_to_video.engine import TextToVideoEngine, TextToVideoConfig
from videotrans.configure import config as cfg

# ── 测试文本 ──
TEST_TEXT = (
    "夏日海边，阳光洒在金色沙滩上，海浪轻轻拍打着海岸。"
    "孩子们在沙滩上奔跑嬉戏，堆起一座座沙堡。"
    "远处海鸥飞翔，蓝天白云下帆船点点。"
    "傍晚时分，夕阳将天空染成橙红色，美不胜收。"
)

# ── 输出目录 ──
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "t2v_test")
os.makedirs(OUT_DIR, exist_ok=True)

print("=" * 60)
print("  文字生视频 · 端到端测试")
print("=" * 60)
print(f"  测试文本: {TEST_TEXT[:40]}...")
print(f"  输出目录: {OUT_DIR}")
print(f"  LLM: {cfg.params.get('t2v_llm_api', '未设置')} / {cfg.params.get('t2v_llm_model', '未设置')}")
print(f"  TTS: {cfg.params.get('tts_voice', 'zh-CN-YunjianNeural')}")
print("=" * 60)

app = QCoreApplication(sys.argv)

engine = TextToVideoEngine()
results: dict = {"shots": [], "narration": "", "video": "", "error": ""}
step_done = threading.Event()


def wait_signal(timeout_sec: float) -> bool:
    """等待信号同时处理 Qt 事件队列"""
    deadline = time.time() + timeout_sec
    while not step_done.is_set():
        app.processEvents()
        if time.time() > deadline:
            return False
        time.sleep(0.1)
    return True


# ── 信号连接 ──
def on_progress(msg, pct):
    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
    print(f"  [{bar}] {pct:3d}% {msg}")


def on_shots_ready(shots):
    results["shots"] = shots
    print(f"\n  ✓ 分镜脚本生成完成，共 {len(shots)} 个镜头:")
    for s in shots:
        kws = ", ".join(s.keywords[:3])
        print(f"    [{s.index}] {s.text[:50]}... ({s.duration:.1f}s) 关键词: {kws}")
    step_done.set()


def on_narration_ready(path):
    results["narration"] = path
    print(f"\n  ✓ 旁白配音生成完成: {os.path.basename(path)}")
    step_done.set()


def on_finished(path):
    results["video"] = path
    print(f"\n  ✓ 视频合成完成: {os.path.basename(path)}")
    step_done.set()


def on_error(msg):
    results["error"] = msg
    print(f"\n  ✗ 错误: {msg}")
    step_done.set()


engine.progress.connect(on_progress)
engine.shots_ready.connect(on_shots_ready)
engine.narration_ready.connect(on_narration_ready)
engine.finished.connect(on_finished)
engine.error.connect(on_error)

# ── 步骤 1: 生成分镜 ──
print("\n── 步骤 1: LLM 分镜分析 ──")
step_done.clear()
engine.generate_storyboard(TEST_TEXT)

if not wait_signal(90):
    print("  ⚠ 分镜生成超时（90秒）")
    if not results["shots"]:
        print("  ✗ 无分镜数据，退出")
        sys.exit(1)

if results["error"] and not results["shots"]:
    print("  ✗ 分镜生成失败，退出")
    sys.exit(1)

# ── 步骤 2: 搜索素材 ──
print("\n── 步骤 2: 搜索素材 ──")

local_dirs = ["/home/deepin/Pictures/Screenshots"]
engine._config.use_local = True
engine._config.local_dirs = local_dirs
engine._config.use_pexels = True
engine._config.pexels_api_key = cfg.params.get("pexels_api_key", "")
engine._config.use_pixabay = False
engine._config.use_comfyui = False

print(f"  素材模式: 本地 + Pexels 在线")
print(f"  本地目录: {local_dirs}")
print(f"  Pexels Key: {'已配置' if engine._config.pexels_api_key else '未配置'}")

shots = results["shots"]
total = len(shots)
material_done_count = [0]


def on_material_ready(index):
    material_done_count[0] += 1
    for s in engine._config.shots:
        if s.index == index:
            src = s.material_source or "none"
            path = os.path.basename(s.material_path) if s.material_path else "无"
            print(f"    [{index}] 素材就绪 ({material_done_count[0]}/{total}): {src} → {path}")
            break


# 断开旧连接，重新连接素材信号
try:
    engine.shot_material_ready.disconnect()
except Exception:
    pass
engine.shot_material_ready.connect(on_material_ready)

engine.acquire_materials(shots)

# 等待所有镜头素材就绪（带 Qt 事件处理）
timeout = 30 + total * 20
start = time.time()
while material_done_count[0] < total:
    app.processEvents()
    time.sleep(0.3)
    if time.time() - start > timeout:
        print(f"  ⚠ 素材搜索超时（已就绪 {material_done_count[0]}/{total}）")
        break

# 从 engine 同步最新 shot 状态
for s in engine._config.shots:
    for orig in shots:
        if orig.index == s.index:
            orig.material_source = s.material_source
            orig.material_path = s.material_path
            break

found = sum(1 for s in shots if s.material_path)
print(f"\n  素材获取完成: {found}/{total} 个镜头有素材")
for s in shots:
    path = os.path.basename(s.material_path) if s.material_path else "无素材"
    print(f"    [{s.index}] {s.material_source:8s} → {path}")

# ── 步骤 3: 生成配音 ──
print("\n── 步骤 3: Edge-TTS 配音 ──")
voice = cfg.params.get("tts_voice", "zh-CN-YunjianNeural")
speed = float(cfg.params.get("tts_speed", 1.2))
print(f"  语音: {voice}  语速: {speed}x")

step_done.clear()
engine.generate_narration(TEST_TEXT, voice, speed)

if not wait_signal(90):
    print("  ⚠ 配音生成超时（90秒）")

if not results["narration"]:
    print("  ⚠ 配音生成失败，将合成纯画面视频（无音频）")

# ── 步骤 4: 合成视频 ──
print("\n── 步骤 4: FFmpeg 合成 ──")
config = TextToVideoConfig()
config.input_text = TEST_TEXT
config.shots = shots
config.use_local = True
config.local_dirs = local_dirs
config.use_pexels = True
config.pexels_api_key = cfg.params.get("pexels_api_key", "")
config.use_pixabay = False
config.use_comfyui = False
config.tts_voice = voice
config.tts_speed = speed
config.orientation = "landscape"
config.resolution = (1280, 720)
config.fps = 25
config.subtitle_enabled = True

print(f"  分辨率: {config.resolution[0]}x{config.resolution[1]}")
print(f"  帧率: {config.fps} fps")
print(f"  镜头数: {len(shots)}")

step_done.clear()
engine.compose_video(config)

if not wait_signal(180):
    print("  ⚠ 视频合成超时（180秒）")

# 最后再处理一轮事件
for _ in range(20):
    app.processEvents()
    time.sleep(0.1)

# ── 结果 ──
print("\n" + "=" * 60)
print("  测试结果")
print("=" * 60)

if results["video"] and os.path.exists(results["video"]):
    size_mb = os.path.getsize(results["video"]) / 1024 / 1024
    import shutil

    final_path = os.path.join(OUT_DIR, "t2v_e2e_test.mp4")
    shutil.copy2(results["video"], final_path)
    print(f"  ✅ 视频生成成功!")
    print(f"     临时路径: {results['video']}")
    print(f"     输出路径: {final_path}")
    print(f"     文件大小: {size_mb:.1f} MB")

    import subprocess

    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", final_path],
            capture_output=True, text=True, timeout=10,
        )
        info = json.loads(probe.stdout)
        fmt = info.get("format", {})
        duration = float(fmt.get("duration", 0))
        streams = info.get("streams", [])
        has_video = any(s.get("codec_type") == "video" for s in streams)
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        print(f"     视频时长: {duration:.1f} 秒")
        print(f"     视频流: {'✓' if has_video else '✗'}")
        print(f"     音频流: {'✓' if has_audio else '✗'}")
    except Exception as e:
        print(f"     ffprobe 分析失败: {e}")
else:
    print(f"  ❌ 视频生成失败")
    if results["error"]:
        print(f"     错误: {results['error']}")

# 保留临时目录用于调试
print(f"\n  临时工作目录: {engine._work_dir}")
print(f"  最终输出目录: {OUT_DIR}")
print("=" * 60)

# 保留临时目录，不清理
# engine.cleanup()
app.quit()
sys.exit(0 if results["video"] else 1)
