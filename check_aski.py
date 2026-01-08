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


def read_state() -> set[str]:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return set([line.strip() for line in f if line.strip()])
    except FileNotFoundError:
        return set()


def write_state(sigs: set[str]):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        f.write(f"# updated_at {ts}\n")
        for s in sorted(sigs):
            f.write(s + "\n")


def parse_dates_times(block: str):
    dt_matches = re.findall(
        r"(\d{1,2}\.\d{1,2}\.\d{4}).{0,60}?(\d{1,2}[:.]\d{2})(?:[:.]\d{2})?",
        block
    )
    range_match = re.search(r"(\d{1,2}[:.]\d{2})\s*[–-]\s*(\d{1,2}[:.]\d{2})", block)

    def to_time_str(t: str) -> str:
        return t.replace(".", ":")

    def to_dt(date_str: str, time_str: str) -> datetime:
        d = datetime.strptime(date_str, "%d.%m.%Y").date()
        hh, mm = map(int, to_time_str(time_str).split(":"))
        return datetime(d.year, d.month, d.day, hh, mm, 0, tzinfo=TR_TZ)

    if len(dt_matches) >= 2:
        (d1, t1), (d2, t2) = dt_matches[0], dt_matches[1]
        return to_dt(d1, t1), to_dt(d2, t2)

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


def extract_blocks(html: str, keyword: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    k = keyword.lower()
    blocks = []
    for i, ln in enumerate(lines):
        if k in ln.lower():
            # Pınarbaşı geçen satırın etrafından blok al (yakın tarih/saat satırlarını yakalamak için)
            start = max(0, i - 12)
            end = min(len(lines), i + 20)
            block = "\n".join(lines[start:end])
            # blokları çok çoğaltmamak için normalize
            block = re.sub(r"[ \t]+", " ", block)
            blocks.append(block)

    # Aynı bloğun tekrar yakalanmasını azalt
    uniq = list(dict.fromkeys(blocks))
    return uniq


def main():
    r = requests.get(URL, timeout=30)
    r.raise_for_status()

    blocks = extract_blocks(r.text, KEYWORD)
    known = read_state()

    if not blocks:
        # Sayfada hiç yoksa state'i sıfırla (istersen bunu kapatabiliriz)
        if known:
            write_state(set())
        return

    current_sigs = set()
    new_blocks = []

    for block in blocks:
        sig = hashlib.sha256(block.encode("utf-8")).hexdigest()
        current_sigs.add(sig)
        if sig not in known:
            new_blocks.append(block)

    # State'i "mevcut kayıtlar" ile güncelle (eski kayıt kalkınca listeden düşsün)
    write_state(current_sigs)

    # Yeni bir şey yoksa sus
    if not new_blocks:
        return

    now = datetime.now(TR_TZ)

    # Tek mesajda özet
    parts = []
    for idx, block in enumerate(new_blocks, start=1):
        start_dt, end_dt = parse_dates_times(block)
        if start_dt and end_dt:
            total_min = int((end_dt - start_dt).total_seconds() // 60)
            if now < start_dt:
                left_min = int((start_dt - now).total_seconds() // 60)
                status = f"⏳ Kalan: {humanize_delta(left_min)}"
            elif start_dt <= now <= end_dt:
                passed_min = int((now - start_dt).total_seconds() // 60)
                status = f"🚱 Başladı: {humanize_delta(passed_min)} önce"
            else:
                status = "✅ Bitmiş olabilir"
            parts.append(
                f"#{idx}\n"
                f"🗓 {start_dt.strftime('%d.%m.%Y %H:%M')} → {end_dt.strftime('%d.%m.%Y %H:%M')}\n"
                f"⏱ Süre: {humanize_delta(total_min)}\n"
                f"{status}"
            )
        else:
            parts.append(f"#{idx}\nTarih/saat alınamadı.\n(Detay için linke bak)")

    msg = (
        "🚱 Pınarbaşı Mah. Su Kesintisi Uyarısı\n"
        
        f"✅ Yeni kayıt sayısı: {len(new_blocks)}\n\n"
        + "\n\n".join(parts)
        + f"\n\n🔗 {URL}\n\n"
        "Not: Aynı kayıtlar tekrar bildirilmez."
    )
    send_telegram(msg)


if __name__ == "__main__":
    main()
