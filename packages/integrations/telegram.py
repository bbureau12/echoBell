# packages/integrations/telegram.py
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    chat_id: str
    enabled: bool = True
    timeout_s: int = 10


def load_telegram_config() -> Optional[TelegramConfig]:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    enabled = (os.getenv("TELEGRAM_ENABLED") or "true").strip().lower() in {"1", "true", "yes", "y"}

    if not enabled:
        return TelegramConfig(token=token, chat_id=chat_id, enabled=False)

    if not token or not chat_id:
        return None

    return TelegramConfig(token=token, chat_id=chat_id, enabled=True)


class TelegramNotifier:
    def __init__(self, cfg: TelegramConfig):
        self.cfg = cfg

    def _post(self, method: str, *, data=None, files=None) -> bool:
        if not self.cfg.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.cfg.token}/{method}"
        # tiny retry (handles flaky wifi / transient 429)
        for attempt in range(3):
            try:
                r = requests.post(url, data=data, files=files, timeout=self.cfg.timeout_s)
                if r.status_code == 429:
                    # Telegram may return retry_after seconds in JSON; best-effort:
                    try:
                        retry_after = int(r.json().get("parameters", {}).get("retry_after", 1))
                    except Exception:
                        retry_after = 1
                    time.sleep(min(5, max(1, retry_after)))
                    continue
                r.raise_for_status()
                return True
            except Exception:
                time.sleep(0.5 * (attempt + 1))
        return False

    def send_message(self, text: str, *, disable_preview: bool = True) -> bool:
        return self._post(
            "sendMessage",
            data={
                "chat_id": self.cfg.chat_id,
                "text": text,
                "disable_web_page_preview": "true" if disable_preview else "false",
            },
        )

    def send_photo(self, photo_path: str, caption: str | None = None) -> bool:
        with open(photo_path, "rb") as f:
            return self._post(
                "sendPhoto",
                data={"chat_id": self.cfg.chat_id, "caption": caption or ""},
                files={"photo": f},
            )
