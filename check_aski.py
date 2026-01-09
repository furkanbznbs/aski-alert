import os
import re
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ASKİ kesinti sayfası
URL = "https://www.aski.gov.tr/tr/kesinti.aspx"

# SADECE bu ilçe geçiyorsa kabul et (Sincan Pınarbaşı için)
DISTRICT_REQUIRED = "sincan"

# Aranacak mahalle kelimesi
KEYWORD = "pınarbaşı"

# Telegram secrets (GitHub Actions -> Secrets)
TOKEN = os.environ["TG_BOT_TOKEN"]
CHAT_ID = os.environ["TG_CHAT_ID"]

# Bildirilmiş kayıtların imzaları burada tutulur
STATE_PATH = "state/pinarbasi_state.txt"

# Saat hesapları için Türkiye saati
TR_TZ = ZoneInfo("Europe/Istanbul")


def send_telegram(text: str):
    api = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(api, data={"chat_id": CHAT_ID, "text": text})
    r.raise_for_status()


def read_state() -> set[str]:
    """
    Daha önce bildirilen kayıt imzalarını oku.
    İlk satır '# updated_at ...' olabilir; onu otomatik görmezden geliriz.
    """
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            sigs = set()
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                sigs.add(line)
            return sigs
    except FileNotFoundError:
        return set()


def write_state(sigs: set[str]):
    """
    Mevcut sayfada gördüğümüz kayıtların imzalarını yaz.
    (Kayıt sayfadan kalkarsa state’ten düşer.)
    """
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        f.write(f"# updated_at {ts}\n")
        for s in sorted(sigs):
            f.write(s + "\n")


def humanize_delta(minutes: int) -> str:
    minutes = abs(int(minutes))
    h = minutes // 60
    m = minutes % 60
    if h == 0:
        return f"{m} dk"
    if m == 0:
        return f"{h} saat"
    return f"{h} saat {m} dk"


def parse_dates_times(block: str):
    """
    Blok içinden en olası başlangıç ve bitiş tarih-saatlerini yakalar.
    Örn:
      - 09.01.2026 09:20:00
      - 09.01.2026 23:55:00
    """
    # dd.mm.yyyy + saat (opsiyonel saniye)
    dt_matches = re.findall(
        r"(\d{1,2}\.\d{1,2}\.\d{4}).{0,80}?(\d{1,2}[:.]\d{2})(?:[:.]\d{2})?",
        block
    )

    # saat aralığı 09:00-21:00 veya 09.00–21.00
    range_match = re.search(
        r"(\d{1,2}[:.]\d{2})\s*[–-]\s*(\d{1,2}[:.]\d{2})",
        block
    )

    def to_time_str(t: str) -> str:
        return t.replace(".", ":")

    def to_dt(date_str: str, time_str: str) -> datetime:
        d = datetime.strptime(date_str, "%d.%m.%Y").date()
        hh, mm = map(int, to_time_str(time_str).split(":"))
        return datetime(d.year, d.month, d.day, hh, mm, 0, tzinfo=TR_TZ)

    # 2 adet tarih+saat yakaladıysak başlangıç/bitiş
    if len(dt_matches) >= 2:
        (d1, t1), (d2, t2) = dt_matches[0], dt_matches[1]
        return to_dt(d1, t1), to_dt(d2, t2)

    # 1 tarih + saat aralığı yakaladıysak aynı güne uygula
    if len(dt_matches) >= 1 and range_match:
        d1, _t = dt_matches[0]
        t_start, t_end = range_match.group(1), range_match.group(2)
        start_dt = to_dt(d1, t_start)
        end_dt = to_dt(d1, t_end)
        if end_dt <= start_dt:
            # geceyi aşan aralık varsa
            end_dt = end_dt.replace(day=end_dt.day + 1)
        return start_dt, end_dt

    return None, None


def extract_blocks(html: str, keyword: str) -> list[str]:
    """
    Sayfadaki metni satırlara böler, keyword geçen satırların çevresinden blok çıkarır.
    İlçe filtresi uygular: DISTRICT_REQUIRED blokta yoksa o kayıt elenir.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    k = keyword.lower()
    blocks = []

    for i, ln in enumerate(lines):
        if k in ln.lower():
            start = max(0, i - 12)
            end = min(len(lines), i + 20)
            block = "\n".join(lines[start:end])
            block_norm = block.lower()

            # İlçe filtresi: Sincan yoksa alma
            if DISTRICT_REQUIRED and DISTRICT_REQUIRED not in block_norm:
                continue

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

    # Sayfada Sincan + Pınarbaşı hiç yoksa: state'i sıfırla ve çık
    if not blocks:
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

    # State’i güncelle (mevcut kayıtlar)
    write_state(current_sigs)

    # Yeni bir şey yoksa sus
    if not new_blocks:
        return

    now = datetime.now(TR_TZ)

    # Tek mesajda yeni kayıt özetle
    parts = []
    for idx, block in enumerate(new_blocks, start=1):
        start_dt, end_dt = parse_dates_times(block)
        if start_dt and end_dt:
            total_min = int((end_dt - start_dt).total_seconds() // 60)

            if now < start_dt:
                left_min = int((start_dt - now).total_seconds() // 60)
                status = f"⏳ Kesintiye kalan: {humanize_delta(left_min)}"
            elif start_dt <= now <= end_dt:
                passed_min = int((now - start_dt).total_seconds() // 60)
                status = f"🚱 Başladı: {humanize_delta(passed_min)} önce"
            else:
                status = "✅ Bitmiş olabilir (sayfada kayıt kalmış olabilir)."

            parts.append(
                f"#{idx}\n"
                f"🗓 {start_dt.strftime('%d.%m.%Y %H:%M')} → {end_dt.strftime('%d.%m.%Y %H:%M')}\n"
                f"⏱ Süre: {humanize_delta(total_min)}\n"
                f"{status}"
            )
        else:
            parts.append(
                f"#{idx}\n"
                "Tarih/saat otomatik çekilemedi.\n"
                "(Detay için linke bak)"
            )

    msg = (
        "🚱 Sincan / Pınarbaşı Su Kesintisi Uyarısı\n"
        f"📍 İlçe filtresi: {DISTRICT_REQUIRED.title()}\n"
        f"✅ Yeni kayıt sayısı: {len(new_blocks)}\n\n"
        + "\n\n".join(parts)
        + f"\n\n🔗 {URL}\n\n"
        "Not: Aynı kayıtlar tekrar bildirilmez."
    )

    send_telegram(msg)


if __name__ == "__main__":
    main()
