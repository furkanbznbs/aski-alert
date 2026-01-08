import os
import re
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

URL = "https://www.aski.gov.tr/tr/kesinti.aspx"
KEYWORD = "pınarbaşı"

TOKEN = os.environ["TG_BOT_TOKEN"]
CHAT_ID = os.environ["TG_CHAT_ID"]

STATE_PATH = "state/pinarbasi_state.txt"
TR_TZ = ZoneInfo("Europe/Istanbul")


def send_telegram(text: str):
    api = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(api, data={"chat_id": CHAT_ID, "text": text})
    r.raise_for_status()


def read_prev_sig() -> str:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return f.readline().strip()
    except FileNotFoundError:
        return ""


def write_state(sig: str, context: str):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        f.write(sig + "\n")
        f.write(ts + "\n")
        f.write(context.strip() + "\n")


def clear_state():
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        f.write("")


def extract_context(html: str, keyword: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    low = text.lower()
    k = keyword.lower()

    idx = low.find(k)
    if idx == -1:
        return ""

    start = max(0, idx - 800)
    end = min(len(text), idx + 1600)
    window = text[start:end]

    window = re.sub(r"[ \t]+", " ", window)
    window = re.sub(r"\n{2,}", "\n", window)
    return window


def parse_dates_times(context: str):
    dt_matches = re.findall(
        r"(\d{1,2}\.\d{1,2}\.\d{4}).{0,60}?(\d{1,2}[:.]\d{2})(?:[:.]\d{2})?",
        context
    )

    range_match = re.search(
        r"(\d{1,2}[:.]\d{2})\s*[–-]\s*(\d{1,2}[:.]\d{2})",
        context
    )

    def to_time_str(t: str) -> str:
        return t.replace(".", ":")

    def to_dt(date_str: str, time_str: str) -> datetime:
        d = datetime.strptime(date_str, "%d.%m.%Y").date()
        hh, mm = map(int, to_time_str(time_str).split(":"))
        return datetime(d.year, d.month, d.day, hh, mm, 0, tzinfo=TR_TZ)

    # 2 adet tarih+saat yakaladıysa -> başlangıç/bitiş
    if len(dt_matches) >= 2:
        (d1, t1), (d2, t2) = dt_matches[0], dt_matches[1]
        return to_dt(d1, t1), to_dt(d2, t2)

    # 1 tarih + saat aralığı yakaladıysa -> aynı güne uygula
    if len(dt_matches) >= 1 and range_match:
        d1, _t = dt_matches[0]
        t_start, t_end = range_match.group(1), range_match.group(2)
        start_dt = to_dt(d1, t_start)
        end_dt = to_dt(d1, t_end)
        if end_dt <= start_dt:
            end_dt = end_dt.replace(day=end_dt.day + 1)
        return start_dt, end_dt

    return None, None


def humanize_delta(minutes: int) -> str:
    minutes = abs(int(minutes))
    h = minutes // 60
    m = minutes % 60
    if h == 0:
        return f"{m} dk"
    if m == 0:
        return f"{h} saat"
    return f"{h} saat {m} dk"


def main():
    r = requests.get(URL, timeout=30)
    r.raise_for_status()

    context = extract_context(r.text, KEYWORD)
    prev_sig = read_prev_sig()

    # Pınarbaşı yoksa state'i temizle (ileride tekrar çıkarsa yeniden bildirsin)
    if not context:
        if prev_sig:
            clear_state()
        return

    # İmza hesapla (aynı kayıt devam ediyorsa bildirim yok)
    sig = hashlib.sha256(context.encode("utf-8")).hexdigest()
    if sig == prev_sig:
        return

    # Yeni/Değişmiş kayıt: tarih-saat yakala ve mesajı oluştur
    start_dt, end_dt = parse_dates_times(context)
    now = datetime.now(TR_TZ)

    if start_dt and end_dt:
        total_min = int((end_dt - start_dt).total_seconds() // 60)

        if now < start_dt:
            left_min = int((start_dt - now).total_seconds() // 60)
            status_line = f"⏳ Kesintiye kalan: {humanize_delta(left_min)}"
        elif start_dt <= now <= end_dt:
            passed_min = int((now - start_dt).total_seconds() // 60)
            status_line = f"🚱 Kesinti başladı: {humanize_delta(passed_min)} önce"
        else:
            status_line = "✅ Kesinti bitmiş olabilir (sayfada kayıt kalmış olabilir)."

        msg = (
            "🚱 ASKİ Su Kesintisi Uyarısı\n"
            "📍 Pınarbaşı Mahallesi\n\n"
            f"🗓 Başlangıç: {start_dt.strftime('%d.%m.%Y %H:%M')}\n"
            f"🗓 Bitiş: {end_dt.strftime('%d.%m.%Y %H:%M')}\n"
            f"⏱ Süre: {humanize_delta(total_min)}\n"
            f"{status_line}\n\n"
            f"🔗 {URL}\n\n"
            "Not: Aynı kayıt durdukça tekrar bildirim gönderilmeyecek."
        )
    else:
        msg = (
            "🚱 ASKİ Su Kesintisi Uyarısı\n"
            "📍 Pınarbaşı Mahallesi\n\n"
            "Pınarbaşı için kesinti kaydı YENİ/DEĞİŞMİŞ görünüyor.\n"
            "Tarih/saat otomatik çekilemedi (sayfa formatı farklı olabilir).\n"
            f"🔗 {URL}\n\n"
            "Not: Aynı kayıt durdukça tekrar bildirim gönderilmeyecek."
        )

    send_telegram(msg)
    write_state(sig, context)


if __name__ == "__main__":
    main()
