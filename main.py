import requests
import re
import json
import os
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL = "@Bankchi_uz"
STATE_FILE = "last_rates.json"
CBU_CURRENCIES = ["USD", "EUR", "RUB", "CNY", "GBP"]
BANK_CURRENCY = "USD"

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

FONT_BOLD_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]
FONT_REGULAR_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def load_font(paths, size):
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL, "text": text, "parse_mode": "HTML"}
    resp = requests.post(url, data=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def send_telegram_photo(image_path, caption=""):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(image_path, "rb") as f:
        files = {"photo": f}
        data = {"chat_id": CHANNEL, "caption": caption, "parse_mode": "HTML"}
        resp = requests.post(url, data=data, files=files, timeout=30)
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
        if code in CBU_CURRENCIES:
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
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    date_match = re.search(r"Yangilangan sana:\s*([\d]{1,2}\s*\w+\s*\d{4}[,]?\s*\d{2}:\d{2})", text)
    updated = date_match.group(1).strip() if date_match else None

    rows = re.findall(
        r"(\d+)\s*gramm\s*([\d\s]+?)\s*so.?m\s*([\d\s]+?)\s*so.?m\s*([\d\s]+?)\s*so.?m", text
    )
    prices = []
    for gram, sell, buyback_ok, _buyback_damaged in rows:
        try:
            prices.append({
                "gram": int(gram),
                "sell": float(sell.replace(" ", "")),
                "buyback_ok": float(buyback_ok.replace(" ", "")),
            })
        except ValueError:
            pass
    return {"updated": updated, "prices": prices}


def get_bank_rate(slug):
    url = f"https://bank.uz/uz/currency/bank/{slug}"
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))

    pattern = rf"Kod {BANK_CURRENCY}\b.*?Sotib olish ([\d\s.]+?) Sotish ([\d\s.]+?) Yangilanish"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        try:
            buy = float(re.sub(r"[^\d.]", "", m.group(1)))
            sell = float(re.sub(r"[^\d.]", "", m.group(2)))
            return {"buy": buy, "sell": sell}
        except ValueError:
            return None
    return None


def get_all_bank_rates():
    all_rates = {}
    for name, slug in BANKS.items():
        try:
            r = get_bank_rate(slug)
            if r:
                all_rates[name] = r
                print(f"{name}: OK -> sotib olish {r['buy']}, sotish {r['sell']}")
            else:
                print(f"{name}: ma'lumot topilmadi")
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
    order = ["USD", "EUR", "RUB", "CNY", "GBP"]
    for code in order:
        if code in rates:
            info = rates[code]
            arrow = "🔺" if info["diff"] > 0 else ("🔻" if info["diff"] < 0 else "➡️")
            lines.append(f"{code} ({info['name']}): {info['rate']:.2f} so'm {arrow} {info['diff']:+.2f}")
    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


def format_forecast_post(cbu_rates):
    lines = ["🔮 <b>Ertangi kurs bo'yicha taxmin</b>"]
    lines.append("<i>(Rasmiy bashorat emas — so'nggi o'zgarish tendensiyasiga asoslangan oddiy izoh)</i>\n")
    usd = cbu_rates.get("USD")
    if usd:
        diff = usd["diff"]
        current = usd["rate"]
        trend = "oshish" if diff > 0 else ("pasayish" if diff < 0 else "barqaror qolish")
        estimated = current + diff
        lines.append(f"So'nggi o'zgarish: {diff:+.2f} so'm")
        est_text = f"{estimated:,.0f}".replace(",", " ")
        lines.append(f"Shu tendensiya davom etsa, ertangi USD kursi taxminan {est_text} so'm atrofida bo'lishi mumkin ({trend} tendensiyasi).")
    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


def format_ranking_post(all_rates):
    buy_sorted = sorted(all_rates.items(), key=lambda x: x[1]["buy"], reverse=True)
    sell_sorted = sorted(all_rates.items(), key=lambda x: x[1]["sell"])

    lines = ["🏆 <b>USD — banklar reytingi (27 ta bank)</b>\n"]
    lines.append("💵 <b>Eng qimmat sotib olayotgan banklar</b>:")
    for name, r in buy_sorted:
        lines.append(f"{name}: {r['buy']:,.0f} so'm".replace(",", " "))

    lines.append("\n💰 <b>Eng arzon sotayotgan banklar</b>:")
    for name, r in sell_sorted:
        lines.append(f"{name}: {r['sell']:,.0f} so'm".replace(",", " "))

    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


def generate_top10_image(buy_sorted_top10):
    width, height = 900, 150 + 68 * len(buy_sorted_top10) + 100
    img = Image.new("RGB", (width, height), color=(18, 28, 58))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / height
        draw.line([(0, y), (width, y)], fill=(int(18 + t * 12), int(28 + t * 22), int(58 + t * 42)))

    title_font = load_font(FONT_BOLD_PATHS, 42)
    header_font = load_font(FONT_BOLD_PATHS, 26)
    row_font = load_font(FONT_REGULAR_PATHS, 28)
    small_font = load_font(FONT_REGULAR_PATHS, 20)

    draw.text((40, 30), "TOP 10 BANK — USD", font=title_font, fill=(255, 255, 255))
    draw.text((40, 88), "Eng qimmat sotib olayotgan banklar", font=header_font, fill=(255, 215, 0))

    y = 150
    row_height = 68
    for i, (name, price) in enumerate(buy_sorted_top10, start=1):
        rank_color = (255, 215, 0) if i <= 3 else (200, 200, 200)
        draw.text((40, y), f"{i}", font=header_font, fill=rank_color)
        draw.text((90, y), name, font=row_font, fill=(255, 255, 255))
        price_text = f"{price:,.0f} so'm".replace(",", " ")
        draw.text((width - 260, y), price_text, font=row_font, fill=(120, 220, 120))
        draw.line([(40, y + row_height - 12), (width - 40, y + row_height - 12)], fill=(80, 90, 120), width=1)
        y += row_height

    draw.text((40, height - 55), "@Bankchi_uz", font=small_font, fill=(180, 190, 210))

    path = "/tmp/top10_usd.png"
    img.save(path)
    return path


def generate_gold_image(gold_data):
    prices = gold_data.get("prices", [])
    width, height = 900, 190 + 70 * len(prices) + 90
    img = Image.new("RGB", (width, height), color=(42, 32, 12))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / height
        draw.line([(0, y), (width, y)], fill=(int(42 + t * 28), int(32 + t * 18), int(12 + t * 6)))

    title_font = load_font(FONT_BOLD_PATHS, 40)
    header_font = load_font(FONT_BOLD_PATHS, 24)
    row_font = load_font(FONT_REGULAR_PATHS, 26)
    small_font = load_font(FONT_REGULAR_PATHS, 18)

    draw.text((40, 30), "OLTIN QUYMALAR NARXI", font=title_font, fill=(255, 215, 0))
    draw.text((40, 85), "Markaziy bank rasmiy narxi", font=header_font, fill=(230, 230, 230))

    draw.text((40, 145), "Og'irligi", font=header_font, fill=(255, 215, 0))
    draw.text((320, 145), "Sotish narxi", font=header_font, fill=(255, 215, 0))
    draw.text((620, 145), "Qaytarib sotib olish", font=header_font, fill=(255, 215, 0))

    y = 195
    row_height = 70
    for item in prices:
        draw.text((40, y), f"{item['gram']} gramm", font=row_font, fill=(255, 255, 255))
        draw.text((320, y), f"{item['sell']:,.0f} so'm".replace(",", " "), font=row_font, fill=(120, 220, 120))
        draw.text((620, y), f"{item['buyback_ok']:,.0f} so'm".replace(",", " "), font=row_font, fill=(210, 210, 210))
        draw.line([(40, y + row_height - 18), (width - 40, y + row_height - 18)], fill=(90, 70, 40), width=1)
        y += row_height

    if gold_data.get("updated"):
        draw.text((40, y + 5), f"Yangilangan: {gold_data['updated']}", font=small_font, fill=(200, 190, 160))

    draw.text((40, height - 45), "@Bankchi_uz", font=small_font, fill=(200, 190, 160))

    path = "/tmp/gold_prices.png"
    img.save(path)
    return path


def main():
    state = load_state()
    new_state = dict(state)

    cbu_rates = get_cbu_rates()
    gold = get_cbu_gold()
    cbu_key = json.dumps(cbu_rates, sort_keys=True) + json.dumps(gold, sort_keys=True)

    if state.get("cbu") != cbu_key:
        send_telegram_message(format_cbu_post(cbu_rates, gold))
        send_telegram_message(format_forecast_post(cbu_rates))
        if gold.get("prices"):
            gold_img = generate_gold_image(gold)
            send_telegram_photo(gold_img, caption="🥇 Oltin quymalar narxi — Markaziy bank")
        new_state["cbu"] = cbu_key
        print("CBU + taxmin + oltin rasmli post yuborildi")
    else:
        print("CBU kursi o'zgarmagan")

    all_rates = get_all_bank_rates()
    print(f"\nJAMI: {len(all_rates)} / {len(BANKS)} ta bankdan ma'lumot olindi\n")
    banks_key = json.dumps(all_rates, sort_keys=True)

    if all_rates and state.get("banks") != banks_key:
        send_telegram_message(format_ranking_post(all_rates))

        buy_sorted = sorted(all_rates.items(), key=lambda x: x[1]["buy"], reverse=True)[:10]
        top10_data = [(name, r["buy"]) for name, r in buy_sorted]
        top10_img = generate_top10_image(top10_data)
        send_telegram_photo(top10_img, caption="🏆 TOP 10 bank — USD eng qimmat sotib olayotgan")

        new_state["banks"] = banks_key
        print("Bank reytingi (matn + rasm) yuborildi")
    else:
        print("Bank kurslari o'zgarmagan yoki mavjud emas")

    save_state(new_state)


if __name__ == "__main__":
    main()
