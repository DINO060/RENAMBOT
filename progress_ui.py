# progress_ui.py
import math, time, asyncio
from typing import Optional

def human_size(n: int) -> str:
    units = ["B","KB","MB","GB","TB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units)-1:
        f /= 1024; i += 1
    return f"{f:.2f} {units[i]}"

def human_time(seconds: float) -> str:
    if seconds <= 0 or math.isinf(seconds) or math.isnan(seconds):
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h: return f"{h}h{m:02d}m{s:02d}s"
    if m: return f"{m}m{s:02d}s"
    return f"{s}s"

def progress_bar(done: int, total: int, width: int = 20) -> str:
    if total <= 0: total = 1
    filled = int(width * done / total)
    filled = min(max(filled, 0), width)
    return "[" + "●"*filled + "○"*(width-filled) + "]"

def render_progress(label: str, current: int, total: int, start_time: float) -> str:
    now = time.time()
    elapsed = now - start_time if start_time else 0.0001
    speed = current / elapsed  # bytes/s
    remain = total - current
    eta = remain / speed if speed > 0 else float("inf")
    pct = (current / total * 100) if total > 0 else 0.0
    bar = progress_bar(current, total, width=20)
    return (
        f"{label}\n"
        f"{bar}\n"
        f"<b>» Size</b> : {human_size(current)} | {human_size(total)}\n"
        f"<b>» Done</b> : {pct:.2f}%\n"
        f"<b>» Speed</b> : {human_size(speed)}/s\n"
        f"<b>» ETA</b> : {human_time(eta)}"
    )

class MessageProgress:
    """Throttles edits to avoid 429 (Too Many Requests)."""
    def __init__(self, message, label="Downloading..", min_interval=2.5):
        self.message = message
        self.label = label
        self.min_interval = min_interval
        self.start = time.time()
        self._last_edit = 0.0

    async def update(self, current: int, total: int, *, label: Optional[str]=None):
        if label: self.label = label
        now = time.time()
        if (now - self._last_edit) < self.min_interval and current < total:
            return
        self._last_edit = now
        try:
            await self.message.edit_text(render_progress(self.label, current, total, self.start), parse_mode='html')
        except Exception:
            # ignore edit collisions
            pass
