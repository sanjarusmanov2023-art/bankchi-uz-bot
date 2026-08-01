import requests
import re
import json
import os
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL = "@Bankchi_uz"
STATE_FILE = "last_rates.json"
CURRENCIES = ["USD", "EUR", "RUB"]


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL, "text": text, "parse_mode": "HTML"}
    resp = requests.post(url, data=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_cbu_rates():
    url = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
    resp = requests.get(url, timeout=15)
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
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    date_match = re.search(r"Yangilangan sana:\s*([\d]{1,2}\s*\w+\s*\d{4}[,]?\s*\d{2}:\d{2})", text)
    updated = date_match.group(1).strip() if date_match else None
    gold_match = re.search(r"5\s*gramm\s*([\d\s]+?)\s*so.?m", text)
    price_5g = gold_match.group(1).replace(" ", "").strip() if gold_match else None
    return {"updated": updated, "price_5g": price_5g}


def get_kapitalbank_rate():
    url = "https://kapitalbank.uz/uz/services/exchange-rates/"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    text = resp.text
    pattern = r"\[code\]\s*=>\s*(\w+).*?\[course_buy\]\s*=>\s*(\d+).*?\[course_sell\]\s*=>\s*(\d+)"
    matches = re.findall(pattern, text, re.DOTALL)
    rates, seen = {}, set()
    for code, buy, sell in matches:
        if code in CURRENCIES and code not in seen:
            rates[code] = {"buy": int(buy), "sell": int(sell)}
            seen.add(code)
    return rates


def get_usd_ranking():
    url = "https://bank.uz/uz/currency"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    strings = list(soup.stripped_strings)

    start_idx, end_idx = None, None
    for i, s in enumerate(strings):
        if "eng yahshi kurslar" in s and start_idx is None:
            start_idx = i
        if "Pul o'tkazmalari kurslari" in s:
            end_idx = i
            break
    if start_idx is None:
        start_idx = 0
    if end_idx is None:
        end_idx = len(strings)
    section = strings[start_idx:end_idx]

    price_re = re.compile(r"^([\d\s]+(?:\.\d+)?)\s*so.?m$", re.IGNORECASE)

    blocks = []
    current_label, current_pairs, prev_text = None, [], None
    for s in section:
        if s in ("Sotib olish", "Sotish"):
            if current_label is not None:
                blocks.append((current_label, current_pairs))
            current_label, current_pairs, prev_text = s, [], None
            continue
        m = price_re.match(s)
        if m and current_label is not None and prev_text and prev_text != "Barcha kurslar":
            price = float(m.group(1).replace(" ", ""))
            current_pairs.append((prev_text, price))
        prev_text = s
    if current_label is not None:
        blocks.append((current_label, current_pairs))

    usd_buy = blocks[0][1] if len(blocks) > 0 else []
    usd_sell = blocks[1][1] if len(blocks) > 1 else []
    return {"buy": usd_buy, "sell": usd_sell}


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


def format_bank_post(bank_rates):
    lines = ["🏦 <b>Banklar kursi</b>\n"]
    for bank_name, rates in bank_rates.items():
        for code, info in rates.items():
            lines.append(f"<b>{bank_name}</b> — {code}: sotib olish {info['buy']}, sotish {info['sell']}")
    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


def format_ranking_post(ranking):
    lines = ["🏆 <b>USD — banklar reytingi</b>\n"]
    buy_sorted = sorted(ranking["buy"], key=lambda x: x[1], reverse=True)
    sell_sorted = sorted(ranking["sell"], key=lambda x: x[1])

    lines.append("💵 <b>Eng qimmat sotib olayotgan banklar</b> (dollaringizni sotmoqchi bo'lsangiz foydali):")
    for name, price in buy_sorted[:10]:
        lines.append(f"{name}: {price:,.0f} so'm".replace(",", " "))

    lines.append("\n💰 <b>Eng arzon sotayotgan banklar</b> (dollar sotib olmoqchi bo'lsangiz foydali):")
    for name, price in sell_sorted[:10]:
        lines.append(f"{name}: {price:,.0f} so'm".replace(",", " "))

    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


def main():
    state = load_state()
    new_state = dict(state)

    # 1) Markaziy bank kursi + oltin
    cbu_rates = get_cbu_rates()
    gold = get_cbu_gold()
    cbu_key = json.dumps(cbu_rates, sort_keys=True) + json.dumps(gold, sort_keys=True)
    if state.get("cbu") != cbu_key:
        send_telegram_message(format_cbu_post(cbu_rates, gold))
        new_state["cbu"] = cbu_key
        print("CBU post yuborildi")
    else:
        print("CBU kursi o'zgarmagan")

    # 2) Kapitalbank
    bank_rates = {}
    try:
        bank_rates["Kapitalbank"] = get_kapitalbank_rate()
    except Exception as e:
        print(f"Kapitalbank xatolik: {e}")

    banks_key = json.dumps(bank_rates, sort_keys=True)
    if bank_rates and state.get("banks") != banks_key:
        send_telegram_message(format_bank_post(bank_rates))
        new_state["banks"] = banks_key
        print("Bank post yuborildi")
    else:
        print("Bank kurslari o'zgarmagan yoki mavjud emas")

    # 3) USD reytingi (bank.uz orqali)
    try:
        ranking = get_usd_ranking()
        ranking_key = json.dumps(ranking, sort_keys=True)
        if ranking["buy"] and state.get("ranking") != ranking_key:
            send_telegram_message(format_ranking_post(ranking))
            new_state["ranking"] = ranking_key
            print("Reyting post yuborildi")
        else:
            print("Reyting o'zgarmagan yoki mavjud emas")
    except Exception as e:
        print(f"Reyting xatolik: {e}")

    save_state(new_state)


if __name__ == "__main__":
    main()
