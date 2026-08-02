import requests
import re
import json
import os
import random
from io import BytesIO
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL = "@Bankchi_uz"
STATE_FILE = "last_rates.json"
CBU_CURRENCIES = ["USD", "EUR", "RUB", "CNY", "GBP"]
BANK_CURRENCY = "USD"
TASHKENT_TZ = timezone(timedelta(hours=5))

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

CURRENCY_FLAG = {"USD": "us", "EUR": "eu", "RUB": "ru", "CNY": "cn", "GBP": "gb"}

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


def now_tashkent_str():
    return datetime.now(TASHKENT_TZ).strftime("%d.%m.%Y %H:%M")


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL, "text": text, "parse_mode": "HTML"}
    resp = requests.post(url, data=payload, timeout=15)
    resp.raise_for_status()
    return resp.json()


def send_telegram_photo(image_path, caption=""):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    full_caption = f"{caption}\n\n{CHANNEL}" if caption else CHANNEL
    with open(image_path, "rb") as f:
        files = {"photo": f}
        data = {"chat_id": CHANNEL, "caption": full_caption, "parse_mode": "HTML"}
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


def vertical_gradient(width, height, top_color, bottom_color):
    img = Image.new("RGB", (width, height), top_color)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        r = int(top_color[0] + (bottom_color[0] - top_color[0]) * t)
        g = int(top_color[1] + (bottom_color[1] - top_color[1]) * t)
        b = int(top_color[2] + (bottom_color[2] - top_color[2]) * t)
        draw.line([(0, y), (width, y)], fill=(r, g, b))
    return img


def draw_zigzag(draw, x0, y0, x1, y1, n_points, amplitude, color, width=3):
    pts = []
    for i in range(n_points + 1):
        x = x0 + (x1 - x0) * i / n_points
        y = y0 + random.uniform(-amplitude, amplitude)
        pts.append((x, y))
    try:
        draw.line(pts, fill=color, width=width, joint="curve")
    except Exception:
        draw.line(pts, fill=color, width=width)
    return pts


def draw_coin_icon(base_img, x, y, size):
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(icon)
    d.ellipse((0, 0, size, size), fill=(215, 218, 224, 255), outline=(140, 145, 155, 255), width=3)
    d.ellipse((size * 0.12, size * 0.12, size * 0.88, size * 0.88), outline=(175, 180, 190, 255), width=2)
    font = load_font(FONT_BOLD_PATHS, int(size * 0.48))
    d_str = "$"
    bbox = d.textbbox((0, 0), d_str, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]), d_str, font=font, fill=(45, 95, 65, 255))
    base_img.paste(icon, (x, y), icon)


def draw_globe_watermark(img, cx, cy, radius, color=(228, 233, 240), width=2):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(*color, 255), width=width)
    for ratio in (0.35, 0.68):
        h = radius * ratio
        d.ellipse((cx - radius, cy - h, cx + radius, cy + h), outline=(*color, 255), width=width)
        w = radius * ratio
        d.ellipse((cx - w, cy - radius, cx + w, cy + radius), outline=(*color, 255), width=width)
    d.line([(cx - radius, cy), (cx + radius, cy)], fill=(*color, 255), width=width)
    d.line([(cx, cy - radius), (cx, cy + radius)], fill=(*color, 255), width=width)
    img.paste(overlay, (0, 0), overlay)


def add_diagonal_watermark(img, text="@BANKCHI_UZ", opacity=32, font_size=100, angle=-25, color=(255, 255, 255)):
    img = img.convert("RGBA")
    width, height = img.size
    txt_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_layer)
    font = load_font(FONT_BOLD_PATHS, font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((width - w) / 2 - bbox[0], (height - h) / 2 - bbox[1]), text, font=font, fill=(*color, opacity))
    txt_layer = txt_layer.rotate(angle, expand=False, resample=Image.BICUBIC)
    combined = Image.alpha_composite(img, txt_layer)
    return combined.convert("RGB")


def draw_gold_bar_icon(base_img, x, y, w, h):
    icon = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(icon)
    top_inset = int(w * 0.18)
    d.polygon([(top_inset, 0), (w - top_inset, 0), (w, h), (0, h)], fill=(212, 175, 55, 255))
    d.polygon([(top_inset, 0), (w - top_inset, 0), (w - top_inset - 10, 12), (top_inset + 10, 12)], fill=(255, 230, 130, 255))
    d.line([(top_inset + 5, int(h * 0.35)), (w - top_inset - 5, int(h * 0.35))], fill=(150, 110, 20, 180), width=2)
    base_img.paste(icon, (x, y), icon)


def fetch_flag(code, width=70):
    try:
        url = f"https://flagcdn.com/w80/{code}.png"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGBA")
        h = int(img.height * width / img.width)
        return img.resize((width, h))
    except Exception as e:
        print(f"Bayroq topilmadi ({code}): {e}")
        return None


def generate_cbu_image(rates):
    order = [c for c in ["USD", "EUR", "RUB", "CNY", "GBP"] if c in rates]
    row_h = 110
    header_h = 210
    width = 1000
    height = header_h + row_h * len(order) + 70

    full = Image.new("RGB", (width, height), (255, 255, 255))
    header = vertical_gradient(width, header_h, (6, 30, 78), (16, 110, 190))
    full.paste(header, (0, 0))
    draw = ImageDraw.Draw(full)

    draw_zigzag(draw, 0, header_h * 0.78, width, header_h * 0.32, 18, 24, (90, 215, 225), 3)
    draw_globe_watermark(full, width * 0.74, header_h + (height - header_h) * 0.52, min(width, height - header_h) * 0.4)
    draw_coin_icon(full, 30, 25, 90)

    title_font = load_font(FONT_BOLD_PATHS, 40)
    date_font = load_font(FONT_BOLD_PATHS, 24)
    draw.text((135, 35), "VALYUTALAR KURSI", font=title_font, fill=(255, 255, 255))
    date_str = rates[order[0]]["date"] if order else ""
    draw.text((135, 90), date_str, font=date_font, fill=(210, 232, 255))

    name_font = load_font(FONT_BOLD_PATHS, 32)
    sub_font = load_font(FONT_REGULAR_PATHS, 19)
    value_font = load_font(FONT_BOLD_PATHS, 36)
    diff_font = load_font(FONT_BOLD_PATHS, 26)

    y = header_h + 20
    for code in order:
        info = rates[code]
        flag = fetch_flag(CURRENCY_FLAG.get(code, "un"), 74)
        if flag:
            full.paste(flag, (40, y + 15), flag)
        draw.text((150, y + 5), code, font=name_font, fill=(20, 30, 60))
        draw.text((150, y + 48), info["name"], font=sub_font, fill=(120, 120, 130))
        rate_text = f"{info['rate']:,.2f}".replace(",", " ")
        draw.text((480, y + 22), rate_text, font=value_font, fill=(20, 30, 60))
        diff = info["diff"]
        arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "→")
        color = (25, 150, 60) if diff > 0 else ((205, 35, 35) if diff < 0 else (120, 120, 120))
        draw.text((800, y + 28), f"{arrow} {diff:+.2f}", font=diff_font, fill=color)
        draw.line([(40, y + row_h - 12), (width - 40, y + row_h - 12)], fill=(230, 230, 235), width=2)
        y += row_h

    draw.text((width - 240, height - 40), "@Bankchi_uz", font=sub_font, fill=(150, 150, 155))
    full = add_diagonal_watermark(full, font_size=85, color=(160, 170, 190), opacity=45)
    path = "/tmp/cbu_rates.png"
    full.save(path)
    return path


def generate_forecast_image(cbu_rates):
    usd = cbu_rates.get("USD")
    if not usd:
        return None
    diff = usd["diff"]
    current = usd["rate"]
    estimated = current + diff
    up = diff >= 0

    top_color = (8, 55, 130) if up else (110, 12, 12)
    bottom_color = (20, 120, 210) if up else (185, 25, 25)
    width, height = 900, 950
    full = vertical_gradient(width, height, top_color, bottom_color)
    draw = ImageDraw.Draw(full)

    for i in range(3):
        draw_zigzag(draw, 0, height * 0.32 + i * 45, width, height * 0.18 + i * 35, 12, 55, (255, 255, 255), 3)

    flag = fetch_flag("us", 130)
    if flag:
        full.paste(flag, (50, 45), flag)

    title_font = load_font(FONT_BOLD_PATHS, 40)
    draw.text((200, 55), "AQSH DOLLARI", font=title_font, fill=(255, 255, 255))
    draw.text((200, 100), "$ DOLLAR", font=title_font, fill=(255, 255, 255))

    date_font = load_font(FONT_BOLD_PATHS, 32)
    draw.text((50, 220), usd.get("date", ""), font=date_font, fill=(255, 255, 255))

    label_font = load_font(FONT_BOLD_PATHS, 26)
    draw.text((50, 310), "KUTILAYOTGAN KURS:", font=label_font, fill=(225, 225, 225))
    big_font = load_font(FONT_BOLD_PATHS, 84)
    est_text = f"{estimated:,.0f}".replace(",", " ")
    draw.text((50, 350), f"{est_text} SO'M", font=big_font, fill=(255, 255, 255))

    watermark_font = load_font(FONT_BOLD_PATHS, 54)
    draw.text((50, 520), "@BANKCHI_UZ", font=watermark_font, fill=(255, 255, 255))

    change_font = load_font(FONT_BOLD_PATHS, 40)
    arrow = "▲" if up else "▼"
    draw.text((50, 650), f"{arrow} {diff:+.0f} SO'M", font=change_font, fill=(255, 255, 255))

    small_font = load_font(FONT_REGULAR_PATHS, 22)
    draw.text((50, 710), "Rasmiy bashorat emas — so'nggi tendensiyaga asoslangan taxmin", font=small_font, fill=(230, 230, 230))
    draw.text((50, height - 55), "@Bankchi_uz", font=small_font, fill=(230, 230, 230))

    full = add_diagonal_watermark(full, font_size=70, opacity=22)
    path = "/tmp/forecast.png"
    full.save(path)
    return path


def generate_gold_image(gold_data):
    prices = gold_data.get("prices", [])
    width = 900
    header_h = 140
    table_header_h = 60
    row_height = 74
    footer_h = 70
    height = header_h + table_header_h + row_height * len(prices) + footer_h

    full = Image.new("RGB", (width, height), (255, 250, 235))
    header = vertical_gradient(width, header_h, (196, 145, 20), (226, 178, 39))
    full.paste(header, (0, 0))
    draw = ImageDraw.Draw(full)

    draw_gold_bar_icon(full, 40, 35, 70, 70)

    title_font = load_font(FONT_BOLD_PATHS, 36)
    header_font = load_font(FONT_BOLD_PATHS, 22)
    row_font = load_font(FONT_REGULAR_PATHS, 26)
    small_font = load_font(FONT_REGULAR_PATHS, 18)

    draw.text((130, 32), "OLTIN QUYMALAR NARXI", font=title_font, fill=(255, 255, 255))
    draw.text((130, 82), "Markaziy bank rasmiy narxi", font=header_font, fill=(255, 245, 220))

    y_th = header_h + 15
    draw.text((40, y_th), "Og'irligi", font=header_font, fill=(150, 110, 20))
    draw.text((320, y_th), "Sotish narxi", font=header_font, fill=(150, 110, 20))
    draw.text((620, y_th), "Qaytarib sotib olish", font=header_font, fill=(150, 110, 20))

    y = header_h + table_header_h
    for item in prices:
        draw.text((40, y), f"{item['gram']} gramm", font=row_font, fill=(70, 50, 15))
        draw.text((320, y), f"{item['sell']:,.0f} so'm".replace(",", " "), font=row_font, fill=(30, 130, 60))
        draw.text((620, y), f"{item['buyback_ok']:,.0f} so'm".replace(",", " "), font=row_font, fill=(120, 95, 55))
        draw.line([(40, y + row_height - 20), (width - 40, y + row_height - 20)], fill=(225, 200, 150), width=1)
        y += row_height

    if gold_data.get("updated"):
        draw.text((40, y + 10), f"Yangilangan: {gold_data['updated']}", font=small_font, fill=(140, 110, 50))
    draw.text((40, height - 40), "@Bankchi_uz", font=small_font, fill=(140, 110, 50))

    full = add_diagonal_watermark(full, font_size=80, color=(180, 140, 40), opacity=45)
    path = "/tmp/gold_prices.png"
    full.save(path)
    return path


def generate_top10_image(buy_sorted_top10):
    row_h = 78
    header_h = 165
    table_header_h = 50
    width = 1000
    height = header_h + table_header_h + row_h * len(buy_sorted_top10) + 70

    full = Image.new("RGB", (width, height), (255, 255, 255))
    header = vertical_gradient(width, header_h, (6, 30, 78), (16, 110, 190))
    full.paste(header, (0, 0))
    draw = ImageDraw.Draw(full)

    draw_globe_watermark(full, width * 0.76, header_h + (height - header_h) * 0.5, min(width, height - header_h) * 0.42)
    draw_coin_icon(full, 30, 25, 80)

    title_font = load_font(FONT_BOLD_PATHS, 36)
    sub_font = load_font(FONT_BOLD_PATHS, 22)
    date_font = load_font(FONT_BOLD_PATHS, 18)
    draw.text((125, 25), "TOP 10 BANK", font=title_font, fill=(255, 255, 255))
    draw.text((125, 74), "$ DOLLAR eng qimmat sotib olayotgan banklar", font=sub_font, fill=(210, 232, 255))
    draw.text((125, 104), now_tashkent_str(), font=date_font, fill=(190, 215, 245))

    col_font = load_font(FONT_BOLD_PATHS, 20)
    y_th = header_h + 12
    draw.text((70, y_th), "Bank", font=col_font, fill=(90, 95, 110))
    draw.text((width - 420, y_th), "Sotib olish", font=col_font, fill=(90, 95, 110))
    draw.text((width - 220, y_th), "Sotish", font=col_font, fill=(90, 95, 110))
    draw.line([(25, header_h + table_header_h - 5), (width - 25, header_h + table_header_h - 5)], fill=(210, 213, 222), width=2)

    name_font = load_font(FONT_BOLD_PATHS, 27)
    price_font = load_font(FONT_BOLD_PATHS, 27)
    rank_font = load_font(FONT_BOLD_PATHS, 28)

    y = header_h + table_header_h
    for i, (name, buy, sell) in enumerate(buy_sorted_top10, start=1):
        rank_color = (16, 100, 190) if i <= 3 else (150, 155, 165)
        if i % 2 == 0:
            draw.rectangle([(0, y), (width, y + row_h)], fill=(246, 248, 251))
        draw.text((25, y + 22), f"{i}", font=rank_font, fill=rank_color)
        draw.text((70, y + 22), name, font=name_font, fill=(25, 30, 48))
        buy_text = f"{buy:,.0f}".replace(",", " ")
        sell_text = f"{sell:,.0f}".replace(",", " ")
        draw.text((width - 420, y + 22), buy_text, font=price_font, fill=(20, 140, 60))
        draw.text((width - 220, y + 22), sell_text, font=price_font, fill=(205, 95, 20))
        draw.line([(25, y + row_h - 4), (width - 25, y + row_h - 4)], fill=(225, 227, 232), width=1)
        y += row_h

    small_font = load_font(FONT_REGULAR_PATHS, 20)
    draw.text((40, height - 45), "@Bankchi_uz", font=small_font, fill=(140, 145, 155))
    full = add_diagonal_watermark(full, font_size=75, color=(160, 170, 190), opacity=40)
    path = "/tmp/top10_usd.png"
    full.save(path)
    return path


def format_buyers_post(all_rates):
    buy_sorted = sorted(all_rates.items(), key=lambda x: x[1]["buy"], reverse=True)
    lines = ["💵 <b>$ DOLLAR — eng qimmat sotib olayotgan banklar</b>"]
    lines.append(f"<i>{now_tashkent_str()} holatiga</i>")
    lines.append("<i>(dollaringizni sotmoqchi bo'lsangiz foydali)</i>\n")
    for name, r in buy_sorted:
        lines.append(f"{name}: {r['buy']:,.0f} so'm".replace(",", " "))
    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


def format_sellers_post(all_rates):
    sell_sorted = sorted(all_rates.items(), key=lambda x: x[1]["sell"])
    lines = ["💰 <b>$ DOLLAR — eng arzon sotayotgan banklar</b>"]
    lines.append(f"<i>{now_tashkent_str()} holatiga</i>")
    lines.append("<i>(dollar sotib olmoqchi bo'lsangiz foydali)</i>\n")
    for name, r in sell_sorted:
        lines.append(f"{name}: {r['sell']:,.0f} so'm".replace(",", " "))
    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


def main():
    state = load_state()
    new_state = dict(state)

    cbu_rates = get_cbu_rates()
    gold = get_cbu_gold()
    cbu_key = json.dumps(cbu_rates, sort_keys=True) + json.dumps(gold, sort_keys=True)

    if state.get("cbu") != cbu_key:
        try:
            cbu_img = generate_cbu_image(cbu_rates)
            send_telegram_photo(cbu_img, caption="📊 Markaziy bank rasmiy kursi")
        except Exception as e:
            print(f"CBU rasm xatolik: {e}")

        try:
            forecast_img = generate_forecast_image(cbu_rates)
            if forecast_img:
                send_telegram_photo(forecast_img, caption="🔮 Ertangi kurs bo'yicha taxmin (rasmiy bashorat emas)")
        except Exception as e:
            print(f"Taxmin rasm xatolik: {e}")

        if gold.get("prices"):
            try:
                gold_img = generate_gold_image(gold)
                send_telegram_photo(gold_img, caption="🥇 Oltin quymalar narxi — Markaziy bank")
            except Exception as e:
                print(f"Oltin rasm xatolik: {e}")

        new_state["cbu"] = cbu_key
        print("CBU rasmli postlar yuborildi")
    else:
        print("CBU kursi o'zgarmagan")

    all_rates = get_all_bank_rates()
    print(f"\nJAMI: {len(all_rates)} / {len(BANKS)} ta bankdan ma'lumot olindi\n")
    banks_key = json.dumps(all_rates, sort_keys=True)

    if all_rates and state.get("banks") != banks_key:
        send_telegram_message(format_buyers_post(all_rates))
        send_telegram_message(format_sellers_post(all_rates))

        try:
            buy_sorted = sorted(all_rates.items(), key=lambda x: x[1]["buy"], reverse=True)[:10]
            top10_data = [(name, r["buy"], r["sell"]) for name, r in buy_sorted]
            top10_img = generate_top10_image(top10_data)
            send_telegram_photo(top10_img, caption="🏆 TOP 10 bank — $ DOLLAR eng qimmat sotib olayotgan")
        except Exception as e:
            print(f"Top10 rasm xatolik: {e}")

        new_state["banks"] = banks_key
        print("Bank reytingi (matn + rasm) yuborildi")
    else:
        print("Bank kurslari o'zgarmagan yoki mavjud emas")

    save_state(new_state)


if __name__ == "__main__":
    main()
