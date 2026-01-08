import os
import re
import hashlib
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

URL = "https://www.aski.gov.tr/tr/kesinti.aspx"
KEYWORD = "pınarbaşı"

TOKEN = os.environ["TG_BOT_TOKEN"]
CHAT_ID = os.environ["TG_CHAT_ID"]

STATE_PATH = "state/pinarbasi_state.txt"


def send_telegram(text: str):
    api = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(api, data={"chat_id": CHAT_ID, "text": text})
    r.raise_for_status()


def read_prev_sig() -> str:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            first = f.readline().strip()
            return first
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
    """
    Sayfa yapısı değişse bile çalışsın diye:
    - metni çıkarıyoruz
    - keyword geçen yerin etrafından bir "bağlam" alıyoruz
    - bunu imzalamak için kullanıyoruz
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    low = text.lower()
    k = keyword.lower()

    idx = low.find(k)
    if idx == -1:
        return ""

    # Keyword'ün geçtiği yerin çevresinden bir pencere al (tarih/saat satırları da yakalansın diye geniş)
    start = max(0, idx - 800)
    end = min(len(text), idx + 1600)
    window = text[start:end]

    # Çok fazla whitespace'i sadeleştir
    window = re.sub(r"[ \t]+", " ", window)
    window = re.sub(r"\n{2,}", "\n", window)
    return window


def main():
    r = requests.get(URL, timeout=30)
    r.raise_for_status()

    context = extract_context(r.text, KEYWORD)

    prev_sig = read_prev_sig()

    # Pınarbaşı yoksa: state'i temizle ki ileride tekrar çıkarsa 1 kere bildirsin
    if not context:
        if prev_sig != "":
            clear_state()
        return

    # Pınarbaşı varsa: bağlamı imzala
    sig = hashlib.sha256(context.encode("utf-8")).hexdigest()

    # Aynı kayıt devam ediyorsa sessiz kal
    if sig == prev_sig:
        return

    # Yeni kayıt tespit edildi: 1 kere bildir + state güncelle
    msg = (
        "🚱 ASKİ Su Kesintisi Uyarısı\n"
        "📍 Pınarbaşı\n\n"
        "Pınarbaşı için kesinti kaydı YENİ/DEĞİŞMİŞ görünüyor.\n"
        f"🔗 {URL}\n\n"
        "Not: Aynı kayıt durdukça tekrar bildirim gönderilmeyecek."
    )
    send_telegram(msg)
    write_state(sig, context)


if __name__ == "__main__":
    main()
