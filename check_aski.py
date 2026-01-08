import os
import re
import requests

URL = "https://www.aski.gov.tr/tr/kesinti.aspx"
KEYWORD = "pınarbaşı"

TOKEN = os.environ["TG_BOT_TOKEN"]
CHAT_ID = os.environ["TG_CHAT_ID"]

def send_telegram(text: str):
    api = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(api, data={"chat_id": CHAT_ID, "text": text})
    r.raise_for_status()

def main():
    r = requests.get(URL, timeout=30)
    r.raise_for_status()

    text = re.sub(r"\s+", " ", r.text).lower()

    if KEYWORD in text:
        msg = (
            "🚱 ASKİ Su Kesintisi Uyarısı\n"
            "📍 Pınarbaşı Mahallesi\n\n"
            "ASKİ kesinti sayfasında Pınarbaşı için kayıt bulundu.\n"
            "Kesinti tarih ve saat bilgisi için aşağıdaki linke bak:\n"
            f"{URL}"
        )
        send_telegram(msg)

if __name__ == "__main__":
    main()
