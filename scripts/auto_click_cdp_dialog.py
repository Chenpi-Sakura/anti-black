"""
auto_click_cdp_dialog.py

监控 Chrome 中的 "委派计划自动化吗？" 对话框 (CDP 连接授权弹窗),
自动勾选 "记住对该网站的设置" 并点击 "允许"。

适用场景:
    MediaCrawler 通过 CDP 模式 (port 1936) 连接已启动的 Chrome 时,
    Chrome 会弹出授权对话框, 本脚本自动放行。

使用方法 (在另一个终端窗口运行, 与爬虫并行):
    conda run -n anti-black python scripts/auto_click_cdp_dialog.py

依赖:
    pip install pywinauto

退出:
    Ctrl+C
"""
import sys
import time
from typing import Optional

try:
    from pywinauto import Desktop
    from pywinauto.controls.uiawrapper import UIAWrapper
except ImportError:
    print("[ERR] 缺少依赖, 请运行: pip install pywinauto", file=sys.stderr)
    sys.exit(1)


ALLOW_TEXTS = ("允许", "Allow", "Allow this time", "允许该网站")
REMEMBER_TEXTS = ("记住对该网站的设置", "记住我的选择", "Remember this decision", "Remember")
CHROME_KEYWORDS = ("Chrome", "chrome", "Chromium")

POLL_INTERVAL = 1.0
CLICK_COOLDOWN = 3.0


def _is_chrome_window(title: str) -> bool:
    return any(kw in title for kw in CHROME_KEYWORDS)


def _try_check_remember(win: UIAWrapper) -> None:
    for text in REMEMBER_TEXTS:
        try:
            cb = win.child_window(title=text, control_type="CheckBox")
            if cb.exists(timeout=0.2):
                state = cb.get_toggle_state()
                if state == 0:
                    cb.toggle()
                    print(f"    [+] 已勾选 '{text}'")
                return
        except Exception:
            continue


def _try_click_allow(win: UIAWrapper) -> bool:
    for text in ALLOW_TEXTS:
        try:
            btn = win.child_window(title=text, control_type="Button")
            if btn.exists(timeout=0.3):
                btn.click_input()
                print(f"    [+] 已点击 '{text}'")
                return True
        except Exception:
            continue
    return False


def scan_once() -> bool:
    try:
        desktop = Desktop(backend="uia")
        for win in desktop.windows():
            try:
                title = win.window_text()
            except Exception:
                continue
            if not title or not _is_chrome_window(title):
                continue
            try:
                # 先尝试勾选 "记住" 再点 "允许", 这样后续就不会再弹了
                _try_check_remember(win)
                if _try_click_allow(win):
                    print(f"[OK] 已处理弹窗 (窗口: {title[:60]})")
                    return True
            except Exception:
                continue
    except Exception as e:
        print(f"[ERR] 桌面扫描失败: {e}", file=sys.stderr)
    return False


def main() -> None:
    print("=" * 60)
    print("Chrome CDP 授权弹窗自动点击器")
    print("=" * 60)
    print(f"轮询间隔: {POLL_INTERVAL}s   点击冷却: {CLICK_COOLDOWN}s")
    print("Ctrl+C 退出\n")

    last_click_ts: float = 0.0
    while True:
        try:
            now = time.time()
            if now - last_click_ts > CLICK_COOLDOWN:
                if scan_once():
                    last_click_ts = time.time()
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print("\n[*] 已退出")
            return
        except Exception as e:
            print(f"[ERR] 主循环异常: {e}", file=sys.stderr)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
