import requests
import re
import json
import os
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL = "@Bankchi_uz"
STATE_FILE = "last_rates.json"
CURRENCIES = ["USD", "EUR", "RUB"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "uz,ru;q=0.9,en;q=0.8",
}

BANKS = {
    "Kapitalbank": "kapitalbank",
    "Agrobank": "agrobank",
    "Ipoteka-bank": "ipoteka-bank",
    "Xalq banki": "xalq-bank",
    "O'zbekiston Milliy banki": "nbu",
    "Asakabank": "asaka-bank",
    "O'zsanoatqurilishbank": "sanoat-qurilish-bank",
    "Turon bank": "turonbank",
    "Aloqabank": "aloqabank",
    "Mikrokreditbank": "mikrokreditbank",
    "Hamkorbank": "hamkorbank",
    "Ipak Yuli Bank": "ipakyulibank",
    "InFinBank": "invest-finance-bank",
    "Orient Finans Bank": "orient-finans-bank",
    "Asia Alliance Bank": "asia-alliance-bank",
    "Anorbank": "anor-bank",
    "Garant bank": "savdogar-bank",
    "Trastbank": "trastbank",
    "Universal bank": "universalbank",
    "Openbank": "smartbank",
    "Octobank": "ravnaq-bank",
    "Hayot Bank": "hayot-bank",
    "BRB": "qishloq-qurilish-bank",
    "Poytaxt bank": "poytaxtbank",
    "Ziraat Bank": "ziraat-bank-uzbekistan",
    "Tenge Bank": "tenge-bank",
    "KDB Bank Uzbekiston": "uzkdb-bank",
}


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL, "text": text, "parse_mode": "HTML"}
    resp = requests.post(url, data=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_cbu_rates():
    url = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    rates = {}
    for item in data:
        code = item.get("Ccy")
        if code in CURRENCIES:
            rates[code] = {
                "name": item.get("CcyNm_UZ"),
                "rate": float(item.get("Rate")),
                "diff": float(item.get("Diff")),
                "date": item.get("Date"),
            }
    return rates


def get_cbu_gold():
    url = "https://cbu.uz/uz/banknotes-coins/gold-bars/prices/"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    date_match = re.search(r"Yangilangan sana:\s*([\d]{1,2}\s*\w+\s*\d{4}[,]?\s*\d{2}:\d{2})", text)
    updated = date_match.group(1).strip() if date_match else None
    gold_match = re.search(r"5\s*gramm\s*([\d\s]+?)\s*so.?m", text)
    price_5g = gold_match.group(1).replace(" ", "").strip() if gold_match else None
    return {"updated": updated, "price_5g": price_5g}


def get_bank_rate(slug, debug=False):
    url = f"https://bank.uz/uz/currency/bank/{slug}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    if debug:
        idx = text.find("Kod ")
        idx2 = text.find("Kod ", idx + 1)
        start = idx2 if idx2 != -1 else idx
        print(f"---- DEBUG [{slug}] matn namunasi ----")
        print(text[max(start, 0):start + 500] if start != -1 else "'Kod' so'zi topilmadi")
        print("---- DEBUG TUGADI ----")

    rates = {}
    for cur in CURRENCIES:
        pattern = rf"Kod {cur}\b.*?Sotib olish ([\d\s.]+?) Sotish ([\d\s.]+?) Yangilanish"
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                buy = float(re.sub(r"[^\d.]", "", m.group(1)))
                sell = float(re.sub(r"[^\d.]", "", m.group(2)))
                rates[cur] = {"buy": buy, "sell": sell}
            except ValueError:
                pass
    return rates


def get_all_bank_rates():
    all_rates = {}
    for i, (name, slug) in enumerate(BANKS.items()):
        try:
            r = get_bank_rate(slug, debug=(i == 0))
            if r:
                all_rates[name] = r
                print(f"{name}: OK -> {list(r.keys())}")
            else:
                print(f"{name}: bo'sh natija (hech narsa topilmadi)")
        except Exception as e:
            print(f"{name} ({slug}) xatolik: {e}")
    return all_rates


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def format_cbu_post(rates, gold):
    lines = ["📊 <b>Markaziy bank rasmiy kursi</b>\n"]
    for code, info in rates.items():
        arrow = "🔺" if info["diff"] > 0 else ("🔻" if info["diff"] < 0 else "➡️")
        lines.append(f"{code} ({info['name']}): {info['rate']:.2f} so'm {arrow} {info['diff']:+.2f}")
    if gold and gold.get("price_5g"):
        lines.append(f"\n🥇 <b>Oltin narxi</b> (5 gramm quyma): {gold['price_5g']} so'm")
        if gold.get("updated"):
            lines.append(f"Yangilangan: {gold['updated']}")
    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


def format_ranking_post(all_rates, currency):
    buy_list, sell_list = [], []
    for name, rates in all_rates.items():
        if currency in rates:
            buy_list.append((name, rates[currency]["buy"]))
            sell_list.append((name, rates[currency]["sell"]))
    buy_sorted = sorted(buy_list, key=lambda x: x[1], reverse=True)
    sell_sorted = sorted(sell_list, key=lambda x: x[1])

    lines = [f"🏆 <b>{currency} — banklar reytingi</b>\n"]
    lines.append("💵 <b>Eng qimmat sotib olayotgan banklar</b> (dollaringizni sotmoqchi bo'lsangiz foydali):")
    for name, price in buy_sorted:
        lines.append(f"{name}: {price:,.0f} so'm".replace(",", " "))

    lines.append("\n💰 <b>Eng arzon sotayotgan banklar</b> (sotib olmoqchi bo'lsangiz foydali):")
    for name, price in sell_sorted:
        lines.append(f"{name}: {price:,.0f} so'm".replace(",", " "))

    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


def main():
    state = load_state()
    new_state = dict(state)

    cbu_rates = get_cbu_rates()
    gold = get_cbu_gold()
    cbu_key = json.dumps(cbu_rates, sort_keys=True) + json.dumps(gold, sort_keys=True)
    if state.get("cbu") != cbu_key:
        send_telegram_message(format_cbu_post(cbu_rates, gold))
        new_state["cbu"] = cbu_key
        print("CBU post yuborildi")
    else:
        print("CBU kursi o'zgarmagan")

    all_rates = get_all_bank_rates()
    print(f"\nJAMI: {len(all_rates)} / {len(BANKS)} ta bankdan ma'lumot olindi\n")
    banks_key = json.dumps(all_rates, sort_keys=True)

    if all_rates and state.get("banks") != banks_key:
        for currency in CURRENCIES:
            send_telegram_message(format_ranking_post(all_rates, currency))
        new_state["banks"] = banks_key
        print("Bank reytingi postlari yuborildi")
    else:
        print("Bank kurslari o'zgarmagan yoki mavjud emas")

    save_state(new_state)


if __name__ == "__main__":
    main()
