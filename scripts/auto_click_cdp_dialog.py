"""
auto_click_cdp_dialog.py

监控屏幕, 找到 Chrome "委派计划自动化" 弹窗中的 "允许" 按钮并自动点击。

实现: OpenCV 多尺度模板匹配 (cv2.matchTemplate) + mss 多屏截屏
    - 模板: assets/cdp_allow_button.png
    - mss 截屏 (绕过 pyautogui 在 Windows 多屏下抓副屏的 bug)
    - 多显示器支持 (ctypes EnumDisplayMonitors), 可通过 --monitor 限定单块屏
    - 多尺度扫描 1.0x ~ 3.0x, 解决模板与屏幕分辨率不匹配的问题
    - 首次命中后缓存 scale, 后续扫描只在该 scale 附近试探
    - 1.5 秒轮询, 3 秒点击冷却

使用方法:
    # 扫所有屏 (默认)
    conda run -n anti-black python scripts/auto_click_cdp_dialog.py
    # 只扫第 2 块屏 (索引 1, 比如用户的竖屏副屏)
    conda run -n anti-black python scripts/auto_click_cdp_dialog.py --monitor 1

退出: Ctrl+C 或鼠标移到屏幕左上角 (pyautogui FAILSAFE)
"""
import argparse
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

# Windows DPI 感知
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import cv2
import mss
import numpy as np
import pyautogui

pyautogui.PAUSE = 0
pyautogui.FAILSAFE = True

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE = SCRIPT_DIR / "assets" / "cdp_allow_button.png"

POLL_INTERVAL = 1.5
CLICK_COOLDOWN = 3.0
CONFIDENCE = 0.7

# 多尺度扫描范围
SCALE_RANGES = [
    (1.0, 3.0, 0.25),
]
LEARNED_SEARCH_RANGE = 0.10
LEARNED_SEARCH_STEP = 0.05


# mss 的 monitors 列表: [0]=合并虚拟桌面, [1..]=各物理屏
# 直接用 mss 的列表更省事
def get_all_monitors() -> list[dict]:
    """用 mss 枚举所有显示器, 返回 [{x, y, w, h, is_primary, name}, ...] 列表 (不含 [0] 合并虚拟桌面)。"""
    with mss.mss() as sct:
        out = []
        for m in sct.monitors[1:]:
            out.append({
                "x": int(m["left"]), "y": int(m["top"]),
                "w": int(m["width"]), "h": int(m["height"]),
                "is_primary": bool(m.get("is_primary", False)),
                "name": m.get("name", ""),
            })
        return out


def pick_target_monitor() -> list[int]:
    """自动选要扫的屏索引列表。优先级: 非主屏竖屏 > 任意竖屏 > 主屏 > [0]。"""
    monitors = get_all_monitors()
    if not monitors:
        return []
    for i, m in enumerate(monitors):
        if m["h"] > m["w"] and not m["is_primary"]:
            return [i]
    for i, m in enumerate(monitors):
        if m["h"] > m["w"]:
            return [i]
    for i, m in enumerate(monitors):
        if m["is_primary"]:
            return [i]
    return [0]


def load_template() -> np.ndarray:
    tpl = cv2.imread(str(TEMPLATE), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        print(f"[ERR] 模板加载失败: {TEMPLATE}", file=sys.stderr)
        sys.exit(1)
    return tpl


def match_at_scale(shot_gray: np.ndarray, tpl_gray: np.ndarray, scale: float) -> tuple[float, tuple[int, int], tuple[int, int]]:
    h, w = tpl_gray.shape[:2]
    new_w, new_h = max(8, int(w * scale)), max(8, int(h * scale))
    if new_w > shot_gray.shape[1] or new_h > shot_gray.shape[0]:
        return 0.0, (0, 0), (0, 0)
    scaled = cv2.resize(tpl_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
    result = cv2.matchTemplate(shot_gray, scaled, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    return float(max_val), max_loc, (new_w, new_h)


def scan_monitor(sct: mss.MSS, tpl_gray: np.ndarray, mon: dict, learned_scale: float | None) -> tuple[tuple[int, int], float, float] | None:
    """扫描单块屏 (用 mss), 返回 (全局坐标, 最佳置信度, 最佳 scale) 或 None。"""
    grab = sct.grab({
        "left": mon["x"], "top": mon["y"],
        "width": mon["w"], "height": mon["h"],
    })
    # mss 返回 BGRA bytes, 转为 numpy 灰度图
    img = np.frombuffer(grab.bgra, dtype=np.uint8).reshape(grab.height, grab.width, 4)
    shot_gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
    # 只扫顶部 1/3, 弹窗总在那里
    h_scan = shot_gray.shape[0] // 3
    if h_scan < shot_gray.shape[0]:
        shot_gray = shot_gray[:h_scan, :]

    if learned_scale is None:
        scales: list[float] = []
        for lo, hi, step in SCALE_RANGES:
            s = lo
            while s <= hi + 1e-6:
                scales.append(round(s, 2))
                s += step
    else:
        scales = [round(learned_scale + d, 2)
                  for d in np.arange(-LEARNED_SEARCH_RANGE, LEARNED_SEARCH_RANGE + 1e-6, LEARNED_SEARCH_STEP)
                  if d > -1e-6 or round(learned_scale + d, 2) > 0]

    best_val = 0.0
    best_loc = (0, 0)
    best_size = (0, 0)
    best_scale = 1.0
    for s in scales:
        val, loc, size = match_at_scale(shot_gray, tpl_gray, s)
        if val > best_val:
            best_val, best_loc, best_size, best_scale = val, loc, size, s

    if best_val < CONFIDENCE:
        return None
    gx = mon["x"] + best_loc[0] + best_size[0] // 2
    gy = mon["y"] + best_loc[1] + best_size[1] // 2
    return (gx, gy), best_val, best_scale


def find_allow_button(sct: mss.MSS, tpl_gray: np.ndarray, learned_scale: float | None, monitor_filter: list[int] | None = None) -> tuple[tuple[int, int], float] | None:
    """扫描指定屏找 '允许' 按钮。monitor_filter=None 表示扫所有屏, 否则只扫指定索引。"""
    monitors = get_all_monitors()
    if monitor_filter is not None:
        monitors = [monitors[i] for i in monitor_filter if 0 <= i < len(monitors)]
    overall_best: tuple[tuple[int, int], float, float] | None = None
    for mon in monitors:
        result = scan_monitor(sct, tpl_gray, mon, learned_scale)
        if result is None:
            continue
        if overall_best is None or result[1] > overall_best[1]:
            overall_best = result
    if overall_best is None:
        return None
    (gx, gy), _, scale = overall_best
    return (gx, gy), scale


def main() -> None:
    parser = argparse.ArgumentParser(description="Chrome CDP 弹窗自动点击器")
    parser.add_argument("--monitor", "-m", type=int, default=None,
                        help="只扫指定索引的显示器 (从 0 开始); 不传则自动选非主屏的竖屏")
    args = parser.parse_args()

    print("=" * 60)
    print("Chrome CDP 弹窗自动点击器 (OpenCV 多尺度 + 多屏)")
    print("=" * 60)
    print(f"模板:   {TEMPLATE}")
    monitors = get_all_monitors()
    print(f"显示器: {len(monitors)} 块")
    for i, m in enumerate(monitors):
        marker = ""
        if args.monitor is not None:
            if i == args.monitor:
                marker = " <-- 指定"
        else:
            if i in pick_target_monitor():
                marker = " <-- 自动选中"
        print(f"  [{i}] x={m['x']:>5} y={m['y']:>5} w={m['w']:>5} h={m['h']:>5}{marker}")
    monitor_filter = [args.monitor] if args.monitor is not None else pick_target_monitor()
    print(f"扫描:   {monitor_filter}")
    print(f"轮询:   {POLL_INTERVAL}s   置信度: {CONFIDENCE}   冷却: {CLICK_COOLDOWN}s")
    print("退出:   Ctrl+C 或鼠标移到屏幕左上角 (FAILSAFE)")
    print()

    tpl_gray = load_template()
    learned_scale: float | None = None
    last_click_ts: float = 0.0
    cycle = 0

    with mss.mss() as sct:
        while True:
            try:
                cycle += 1
                now = time.time()
                if now - last_click_ts > CLICK_COOLDOWN:
                    result = find_allow_button(sct, tpl_gray, learned_scale, monitor_filter)
                    if result is not None:
                        (x, y), scale = result
                        pyautogui.click(x, y, duration=0.1)
                        print(f"[OK] #{cycle:04d} 已点击 '允许' @ ({x}, {y})  scale={scale:.2f}")
                        learned_scale = scale
                        last_click_ts = time.time()
                if cycle % 5 == 0:
                    print(f"[*] #{cycle:04d} 仍在监听... learned_scale={learned_scale}")
                time.sleep(POLL_INTERVAL)
            except KeyboardInterrupt:
                print("\n[*] 已退出")
                return
            except pyautogui.FailSafeException:
                print("\n[!] FAILSAFE 触发, 已退出")
                return
            except Exception as e:
                print(f"[ERR] {e}", file=sys.stderr)
                time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
