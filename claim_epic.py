"""Epic Games 免費遊戲自動領取（直接在 Epic 啟動器裡點選）

流程：開啟啟動器的商店 → 用 Windows 內建 OCR 找「現在免費」的遊戲 → 點進去 →
按「取得」→ 按「下訂單」。遇到人機驗證或登入畫面就停下來通知你手動處理。
"""
import ctypes
import datetime
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# 必須在其他 GUI 套件之前設定，讓座標都是實際像素
ctypes.windll.shcore.SetProcessDpiAwareness(2)

# 套件裝在專案的 lib 資料夾，排程執行時也找得到
import site
site.addsitedir(str(Path(__file__).resolve().parent / "lib"))

import winocr
from PIL import ImageGrab
from pywinauto import Desktop, mouse, keyboard

BASE = Path(__file__).resolve().parent
LOG_FILE = BASE / "claim_log.txt"
SHOT_DIR = BASE / "screenshots"
STORE_URI = "com.epicgames.launcher://store/free-games"
OCR_LANG = "zh-Hant-TW"

FREE_BADGES = ["現在免費", "免費領取", "FREENOW"]
OWNED = ["在收藏庫中", "已擁有", "INLIBRARY", "OWNED"]
GET_BUTTONS = ["獲取", "取得", "GET"]
ORDER_BUTTONS = ["新增至收藏庫", "下訂單", "PLACEORDER", "ADDTOLIBRARY"]
DONE_TEXTS = ["感謝訂購", "感謝您", "檢視收藏庫", "THANKYOU"]
CLOSE_DONE = ["繼續瀏覽", "CONTINUEBROWSING"]
CAPTCHA = ["HCAPTCHA", "我是人類", "人機驗證", "請驗證", "IAMHUMAN"]
LOGIN = ["登入", "SIGNIN"]

# OCR 常把繁體字讀成長得很像的異體字
OCR_FIX = str.maketrans({"増": "增", "獲": "獲", "內": "內", "内": "內", "亅": "」"})

TASK_NAME = "Epic 免費遊戲自動領取"
RUN_DELAY = datetime.timedelta(minutes=10)  # 換檔後多等幾分鐘再領
next_switch = None  # 目前免費遊戲的截止時間（＝下一套開放領取的時間）

if sys.stdout:  # 用 pythonw 執行時沒有主控台
    sys.stdout.reconfigure(encoding="utf-8")


def log(msg):
    line = f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def notify(msg):
    if "--quiet" in sys.argv:
        return
    ctypes.windll.user32.MessageBoxW(0, msg, "Epic 免費遊戲領取", 0x40 | 0x40000)


def get_window():
    for _ in range(60):
        for w in Desktop(backend="win32").windows(visible_only=False):
            if (w.window_text() or "").startswith("Epic Games"):
                return w
        time.sleep(2)
    raise RuntimeError("找不到 Epic Games 啟動器視窗")


def focus(w):
    if w.is_minimized() or not w.is_visible():
        w.restore()
    w.maximize()
    w.set_focus()
    set_topmost(w, True)  # 避免被其他「最上層」視窗擋住按鈕
    time.sleep(1)


def minimize_topmost_blockers(w):
    """把擋在 Epic 前面的「最上層」一般視窗暫時縮小，回傳它們的 handle 以便還原"""
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    GWL_STYLE, GWL_EXSTYLE = -16, -20
    WS_MINIMIZEBOX, WS_EX_TOPMOST, WS_EX_TRANSPARENT = 0x20000, 0x8, 0x20
    r = w.rectangle()
    blockers = []

    def cb(hwnd, _):
        if hwnd == w.handle or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if not (ex & WS_EX_TOPMOST) or ex & WS_EX_TRANSPARENT or not (style & WS_MINIMIZEBOX):
            return True
        rc = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rc))
        if rc.left < r.right and rc.right > r.left and rc.top < r.bottom and rc.bottom > r.top:
            blockers.append(hwnd)
        return True

    proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(cb)
    user32.EnumWindows(proc, 0)
    for h in blockers:
        user32.ShowWindow(h, 6)  # SW_MINIMIZE
    return blockers


def restore_windows(handles):
    for h in handles:
        ctypes.windll.user32.ShowWindow(h, 9)  # SW_RESTORE


def set_topmost(w, on):
    HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
    SWP_NOMOVE, SWP_NOSIZE = 0x2, 0x1
    ctypes.windll.user32.SetWindowPos(
        w.handle, HWND_TOPMOST if on else HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)


def read_screen(w):
    """回傳 (文字, 螢幕中心x, 螢幕中心y) 的清單，文字已去空白並轉大寫"""
    r = w.rectangle()
    img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
    result = winocr.recognize_pil_sync(img, OCR_LANG)
    lines = []
    for line in result["lines"]:
        words = [wd["bounding_rect"] for wd in line["words"]]
        x0 = min(b["x"] for b in words)
        y0 = min(b["y"] for b in words)
        x1 = max(b["x"] + b["width"] for b in words)
        y1 = max(b["y"] + b["height"] for b in words)
        text = line["text"].replace(" ", "").upper().translate(OCR_FIX)
        lines.append((text, int(r.left + (x0 + x1) / 2), int(r.top + (y0 + y1) / 2)))
    return lines, img


def find(lines, keys, exact=False):
    for text, x, y in lines:
        for k in keys:
            if (text == k) if exact else (k in text):
                return text, x, y
    return None


def has(lines, keys):
    return find(lines, keys) is not None


def click(x, y):
    mouse.click(coords=(x, y))


def save_shot(img, name):
    SHOT_DIR.mkdir(exist_ok=True)
    path = SHOT_DIR / f"{datetime.datetime.now():%Y%m%d_%H%M%S}_{name}.png"
    img.save(path)
    return path


def wait_for(w, keys, timeout=20, exact=False):
    """等到畫面出現 keys 其中之一，回傳 (命中, lines, img)"""
    end = time.time() + timeout
    while True:
        lines, img = read_screen(w)
        hit = find(lines, keys, exact)
        if hit or time.time() > end:
            return hit, lines, img
        time.sleep(1.5)


def open_store(w):
    """點左側選單的「商店」回到商店首頁"""
    focus(w)
    r = w.rectangle()
    lines, img = read_screen(w)
    sidebar = [(t, x, y) for t, x, y in lines if x < r.left + (r.right - r.left) * 0.15]
    hit = find(sidebar, ["商店", "STORE"], exact=True)
    if not hit:  # 可能有殘留的結帳視窗蓋住，先關掉再試
        keyboard.send_keys("{ESC}")
        time.sleep(2)
        lines, img = read_screen(w)
        sidebar = [(t, x, y) for t, x, y in lines if x < r.left + (r.right - r.left) * 0.15]
        hit = find(sidebar, ["商店", "STORE"], exact=True)
    if not hit:  # 選單反白時有時辨識不到，改點上方的「探索」
        hit = find(lines, ["探索", "DISCOVER"], exact=True)
    if not hit:
        raise NeedsHuman(f"找不到左側「商店」選單（截圖：{save_shot(img, 'no_store')}）")
    click(hit[1], hit[2])
    time.sleep(6)
    scroll_top(w)


def parse_end_time(lines):
    """從「目前免費，10月22日下午11:00截止」這類文字取出截止時間"""
    pat = re.compile(r"(\d{1,2})月(\d{1,2})日(上午|下午)?(\d{1,2}):(\d{2})截止")
    now = datetime.datetime.now()
    for text, _, _ in lines:
        m = pat.search(text)
        if not m:
            continue
        month, day, ampm, hour, minute = m.groups()
        hour = int(hour) % 12 + (12 if ampm == "下午" else 0) if ampm else int(hour)
        dt = datetime.datetime(now.year, int(month), int(day), hour, int(minute))
        if dt < now - datetime.timedelta(days=180):  # 跨年
            dt = dt.replace(year=now.year + 1)
        return dt
    return None


def schedule_next(dt):
    """把排程改成：下一套開放後 10 分鐘執行一次，另保留每週五中午當備援"""
    when = (dt + RUN_DELAY).strftime("%Y-%m-%dT%H:%M:%S")
    ps = (
        f"$t1 = New-ScheduledTaskTrigger -Once -At '{when}';"
        "$t2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 12:00;"
        f"Set-ScheduledTask -TaskName '{TASK_NAME}' -Trigger $t1,$t2 | Out-Null"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, creationflags=0x08000000)
    if r.returncode == 0:
        log(f"下次自動執行：{dt + RUN_DELAY:%Y-%m-%d %H:%M}")
    else:
        log(f"更新排程失敗：{r.stderr.strip()}")


def find_free_cards(w):
    """在商店頁往下捲，找出所有「現在免費」的卡片位置"""
    global next_switch
    for _ in range(12):
        lines, _ = read_screen(w)
        next_switch = next_switch or parse_end_time(lines)
        cards = []
        for t, x, y in lines:
            if any(k in t for k in FREE_BADGES):
                # 卡片標題在徽章正下方
                below = [(tt, tx, ty) for tt, tx, ty in lines if 0 < ty - y < 150 and abs(tx - x) < 400]
                top = min((ty for _, _, ty in below), default=0)
                title = "".join(tt for tt, _, ty in sorted(below, key=lambda b: b[1]) if ty - top < 25)
                cards.append((x, y, title or "?"))
        if cards:
            return sorted(cards)
        r = w.rectangle()
        mouse.scroll(coords=((r.left + r.right) // 2, (r.top + r.bottom) // 2), wheel_dist=-5)
        time.sleep(1.5)
    return []


def scroll_top(w):
    r = w.rectangle()
    for _ in range(4):
        mouse.scroll(coords=((r.left + r.right) // 2, (r.top + r.bottom) // 2), wheel_dist=15)
        time.sleep(0.3)
    time.sleep(1)


class NeedsHuman(Exception):
    pass


def page_title(w, lines):
    """遊戲頁最上方的大標題（位於導覽列和分頁標籤之間）"""
    r = w.rectangle()
    h, wd = r.bottom - r.top, r.right - r.left
    for t, x, y in lines:
        if x > r.left + wd * 0.15 and r.top + h * 0.11 < y < r.top + h * 0.20 and len(t) >= 2:
            return t
    return None


def claim_current_page(w, title):
    """在遊戲頁面上：已擁有回傳 'owned'，成功回傳 'claimed'"""
    time.sleep(3)
    scroll_top(w)
    hit, lines, img = wait_for(w, OWNED + GET_BUTTONS, exact=False)
    title = page_title(w, lines) or title
    if has(lines, OWNED):
        log(f"已擁有：{title}")
        return "owned", title
    btn = find(lines, GET_BUTTONS, exact=True)
    if not btn:
        raise NeedsHuman(f"找不到「獲取」按鈕（截圖：{save_shot(img, 'no_get')}）")
    click(btn[1], btn[2])
    log(f"按下「獲取」：{title}")

    hit, lines, img = wait_for(w, ORDER_BUTTONS + CAPTCHA, timeout=30, exact=True)
    if has(lines, CAPTCHA):
        raise NeedsHuman(f"出現人機驗證，請手動完成：{title}")
    btn = find(lines, ORDER_BUTTONS, exact=True)  # 說明文字裡也有同樣字眼，要找整行的按鈕
    if not btn:
        raise NeedsHuman(f"找不到「新增至收藏庫」（截圖：{save_shot(img, 'no_order')}）")
    click(btn[1], btn[2])
    log("按下「新增至收藏庫」")

    hit, lines, img = wait_for(w, DONE_TEXTS + OWNED + CAPTCHA, timeout=40)
    if has(lines, CAPTCHA):
        raise NeedsHuman(f"出現人機驗證，請手動完成：{title}")
    if not hit:
        raise NeedsHuman(f"無法確認是否領取成功（截圖：{save_shot(img, 'unknown')}）")
    log(f"領取成功：{title}")
    btn = find(lines, CLOSE_DONE, exact=True)
    if btn:
        click(btn[1], btn[2])
    else:
        keyboard.send_keys("{ESC}")
    time.sleep(2)
    return "claimed", title


def main():
    log("===== 開始 =====")
    os.startfile(STORE_URI)
    w = get_window()
    time.sleep(10)  # 等啟動器載入
    focus(w)
    blockers = minimize_topmost_blockers(w)
    focus(w)

    claimed, owned = [], []
    try:
        return run(w, claimed, owned)
    finally:
        set_topmost(w, False)
        restore_windows(blockers)
        if next_switch and next_switch > datetime.datetime.now():
            schedule_next(next_switch)


def run(w, claimed, owned):
    index = 0
    try:
        while True:
            open_store(w)
            cards = find_free_cards(w)
            if not cards:
                lines, img = read_screen(w)
                if has(lines, LOGIN) and not has(lines, ["收藏庫", "LIBRARY"]):
                    raise NeedsHuman("啟動器尚未登入，請先登入 Epic 帳號")
                raise NeedsHuman(f"找不到「現在免費」的遊戲（截圖：{save_shot(img, 'no_cards')}）")
            if index >= len(cards):
                break
            log(f"免費遊戲 {index + 1}/{len(cards)}")
            x, y, title = cards[index]
            click(x, y)
            status, title = claim_current_page(w, title)
            (claimed if status == "claimed" else owned).append(title)
            index += 1
    except NeedsHuman as e:
        log(f"需要手動處理：{e}")
        notify(f"需要你手動處理：\n{e}")
        return 1
    except Exception as e:
        log(f"錯誤：{e!r}")
        notify(f"領取程式發生錯誤：\n{e!r}")
        return 1

    log(f"完成：新領取 {len(claimed)} 款，已擁有 {len(owned)} 款")
    if claimed:
        notify("已領取：\n" + "\n".join(claimed))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"錯誤：{e!r}")
        notify(f"領取程式發生錯誤：\n{e!r}")
        sys.exit(1)
