import requests
import re
import json
import os
import random
from io import BytesIO
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageFilter

TASHKENT_TZ = timezone(timedelta(hours=5))


def now_tashkent_str():
    return datetime.now(TASHKENT_TZ).strftime("%d.%m.%Y %H:%M")


BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL = "@Bankchi_uz"
STATE_FILE = "last_rates.json"
CBU_CURRENCIES = ["USD", "EUR", "RUB", "CNY", "GBP"]
BANK_CURRENCY = "USD"
BANK_TIP = "✅ Banklarga borishdan oldin valyuta kursini albatta tekshiring!"
UZRVB_NEWS_URL = "https://uzrvb.uz/oz/press-center/yangiliklar-va-elonlar/"

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


# ============================================================
#  TELEGRAM YUBORISH
# ============================================================

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHANNEL, "text": text, "parse_mode": "HTML"}
    resp = requests.post(url, data=payload, timeout=30)
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


# ============================================================
#  MA'LUMOT OLISH (CBU, OLTIN, BANKLAR)
# ============================================================

def get_cbu_rates():
    url = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
    resp = requests.get(url, headers=HEADERS, timeout=30)
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
    resp = requests.get(url, headers=HEADERS, timeout=30)
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
    resp = requests.get(url, headers=HEADERS, timeout=30)
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


def get_latest_uzrvb_news():
    """UzRVB (valyuta birjasi) saytidan eng so'nggi yangilikni oladi."""
    resp = requests.get(UZRVB_NEWS_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/yangiliklar-va-elonlar/" in href and href.endswith(".htm") and "page" not in href.lower():
            title = a.get_text(strip=True)
            if title and len(title) > 10:
                full_url = href if href.startswith("http") else f"https://uzrvb.uz{href}"
                candidates.append((full_url, title))

    if not candidates:
        print("UzRVB: yangilik havolalari topilmadi (sayt strukturasi o'zgargan bo'lishi mumkin)")
        return None

    news_url, news_title = candidates[0]

    date_str = None
    excerpt = ""
    try:
        art_resp = requests.get(news_url, headers=HEADERS, timeout=30)
        art_resp.raise_for_status()
        art_soup = BeautifulSoup(art_resp.text, "html.parser")
        art_text = re.sub(r"\s+", " ", art_soup.get_text(" ", strip=True))
        date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", art_text)
        date_str = date_match.group(1) if date_match else None
        idx = art_text.find(news_title)
        if idx != -1:
            excerpt = art_text[idx + len(news_title):idx + len(news_title) + 400].strip()
        else:
            excerpt = art_text[:400]
    except Exception as e:
        print(f"UzRVB maqola sahifasini o'qishda xatolik: {e}")

    if not date_str:
        date_str = now_tashkent_str()[:10]

    return {"title": news_title, "url": news_url, "date": date_str, "excerpt": excerpt}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ============================================================
#  DIZAYN YORDAMCHILARI
# ============================================================

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


def radial_glow(width, height, cx, cy, radius, color, max_alpha=70):
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    steps = 60
    for i in range(steps, 0, -1):
        a = int(max_alpha * (i / steps) ** 2)
        r = radius * i / steps
        gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*color, a))
    return glow


def dot_grid(width, height, spacing=34, radius=1, color=(255, 255, 255), alpha=18):
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for x in range(0, width, spacing):
        for y in range(0, height, spacing):
            d.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*color, alpha))
    return layer


def rounded_rect(draw, box, radius, fill=None, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_pill(draw, cx, cy, text, font, fg, bg, pad_x=16, pad_y=8):
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    box = (cx - w / 2 - pad_x, cy - h / 2 - pad_y - bbox[1], cx + w / 2 + pad_x, cy + h / 2 + pad_y - bbox[1])
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) / 2, fill=bg)
    draw.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), text, font=font, fill=fg)


def soft_shadow_text(base_rgba, pos, text, font, fill, blur=10, offset=(0, 8), shadow_alpha=120):
    x, y = pos
    shadow_layer = Image.new("RGBA", base_rgba.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    sd.text((x + offset[0], y + offset[1]), text, font=font, fill=(0, 0, 0, shadow_alpha))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(blur))
    base_rgba.alpha_composite(shadow_layer)
    d = ImageDraw.Draw(base_rgba)
    d.text((x, y), text, font=font, fill=fill)


def draw_money_badge(base_img, x, y, size):
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(badge)
    note_w, note_h = int(size * 0.86), int(size * 0.55)
    note = Image.new("RGBA", (note_w + 20, note_h + 20), (0, 0, 0, 0))
    nd = ImageDraw.Draw(note)
    nd.rounded_rectangle((10, 10, note_w + 10, note_h + 10), radius=10, fill=(235, 244, 255, 255), outline=(150, 180, 220, 255), width=2)
    nd.rounded_rectangle((22, 22, note_w - 2, note_h - 2), radius=6, outline=(180, 205, 235, 255), width=1)
    note = note.rotate(-16, expand=True, resample=Image.BICUBIC)
    badge.paste(note, (int(size * 0.02), int(size * 0.30)), note)
    coin_d = int(size * 0.62)
    cx, cy = int(size * 0.55), int(size * 0.42)
    d.ellipse((cx - coin_d // 2, cy - coin_d // 2, cx + coin_d // 2, cy + coin_d // 2), fill=(255, 205, 60, 255), outline=(200, 150, 20, 255), width=3)
    d.ellipse((cx - coin_d // 2 + 7, cy - coin_d // 2 + 7, cx + coin_d // 2 - 7, cy + coin_d // 2 - 7), outline=(230, 180, 50, 255), width=2)
    dollar_font = load_font(FONT_BOLD_PATHS, int(coin_d * 0.5))
    bbox = d.textbbox((0, 0), "$", font=dollar_font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), "$", font=dollar_font, fill=(140, 95, 10, 255))
    base_img.paste(badge, (x, y), badge)


def draw_gold_bar_badge(base_img, x, y, size):
    badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(badge)
    w, h = int(size * 0.9), int(size * 0.55)
    ox, oy = int(size * 0.05), int(size * 0.28)
    top_inset = int(w * 0.16)
    d.polygon([(ox + top_inset, oy), (ox + w - top_inset, oy), (ox + w, oy + h), (ox, oy + h)], fill=(255, 210, 90, 255), outline=(180, 130, 20, 255))
    d.polygon([(ox + top_inset, oy), (ox + w - top_inset, oy), (ox + w - top_inset - 10, oy + 12), (ox + top_inset + 10, oy + 12)], fill=(255, 238, 170, 255))
    d.line([(ox + top_inset + 8, oy + int(h * 0.4)), (ox + w - top_inset - 8, oy + int(h * 0.4))], fill=(190, 140, 30, 180), width=2)
    base_img.paste(badge, (x, y), badge)


def draw_rank_badge(draw, cx, cy, r, num, top3=False):
    fill = (255, 215, 80) if top3 else (230, 233, 240)
    outline = (200, 150, 20) if top3 else (190, 195, 205)
    text_fill = (110, 75, 10) if top3 else (110, 115, 128)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=2)
    f = load_font(FONT_BOLD_PATHS, int(r * 1.05))
    t = str(num)
    bbox = draw.textbbox((0, 0), t, font=f)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1]), t, font=f, fill=text_fill)


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


def fetch_flag(code, width=92):
    try:
        url = f"https://flagcdn.com/w80/{code}.png"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content)).convert("RGBA")
        h = int(img.height * width / img.width)
        return img.resize((width, h), Image.LANCZOS)
    except Exception as e:
        print(f"Bayroq topilmadi ({code}): {e}")
        return None


# ============================================================
#  RASM YARATISH
# ============================================================

def generate_cbu_image(rates):
    order = [c for c in ["USD", "EUR", "RUB", "CNY", "GBP"] if c in rates]
    row_h = 158
    header_h = 300
    width = 1500
    card_pad = 40
    height = header_h + row_h * len(order) + 90

    canvas = Image.new("RGBA", (width, height), (244, 247, 251, 255))
    header = vertical_gradient(width, header_h + 30, (5, 22, 66), (18, 96, 175)).convert("RGBA")
    header.alpha_composite(radial_glow(width, header_h + 30, width * 0.85, -40, 420, (80, 190, 255), 90))
    header.alpha_composite(dot_grid(width, header_h + 30, spacing=30, alpha=14))
    canvas.alpha_composite(header, (0, 0))
    draw = ImageDraw.Draw(canvas)

    draw_money_badge(canvas, 44, 40, 120)

    title_font = load_font(FONT_BOLD_PATHS, 56)
    sub_font = load_font(FONT_REGULAR_PATHS, 28)
    date_font = load_font(FONT_BOLD_PATHS, 30)

    draw.text((188, 46), "VALYUTALAR KURSI", font=title_font, fill=(255, 255, 255))
    draw.text((188, 112), "Markaziy bank rasmiy ma'lumotlari", font=sub_font, fill=(190, 215, 245))
    date_str = rates[order[0]]["date"] if order else now_tashkent_str()
    draw_pill(draw, width - 150, 62, date_str, date_font, (15, 40, 90), (255, 255, 255))

    name_font = load_font(FONT_BOLD_PATHS, 44)
    sub2_font = load_font(FONT_REGULAR_PATHS, 26)
    value_font = load_font(FONT_BOLD_PATHS, 50)
    pill_font = load_font(FONT_BOLD_PATHS, 30)

    y = header_h + 24
    for code in order:
        info = rates[code]
        card_box = (card_pad, y, width - card_pad, y + row_h - 16)
        rounded_rect(draw, card_box, 22, fill=(255, 255, 255))

        flag = fetch_flag(CURRENCY_FLAG.get(code, "un"), 92)
        if flag:
            fw, fh = flag.size
            fy = y + (row_h - 16 - fh) // 2
            mask = Image.new("L", flag.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, fw, fh), radius=10, fill=255)
            canvas.paste(flag, (card_pad + 26, fy), mask)

        tx = card_pad + 26 + 92 + 26
        draw.text((tx, y + 22), code, font=name_font, fill=(20, 30, 60))
        draw.text((tx, y + 78), info["name"], font=sub2_font, fill=(120, 128, 145))

        rate_text = f"{info['rate']:,.2f}".replace(",", " ")
        rbbox = draw.textbbox((0, 0), rate_text, font=value_font)
        rw = rbbox[2] - rbbox[0]
        draw.text((width - 460 - rw, y + (row_h - 16 - (rbbox[3] - rbbox[1])) // 2 - rbbox[1]), rate_text, font=value_font, fill=(20, 30, 60))

        diff = info["diff"]
        up = diff > 0
        flat = diff == 0
        arrow = "▲" if up else ("▼" if not flat else "→")
        pill_bg = (224, 247, 232) if up else ((252, 228, 228) if not flat else (235, 235, 238))
        pill_fg = (20, 140, 70) if up else ((195, 40, 40) if not flat else (110, 110, 115))
        draw_pill(draw, width - card_pad - 140, y + (row_h - 16) // 2, f"{arrow} {diff:+.2f}", pill_font, pill_fg, pill_bg)

        y += row_h

    small_font = load_font(FONT_REGULAR_PATHS, 28)
    draw.text((card_pad, height - 56), "@Bankchi_uz", font=small_font, fill=(140, 148, 165))
    full_rgb = canvas.convert("RGB")
    full_rgb = add_diagonal_watermark(full_rgb, font_size=120, color=(150, 165, 195), opacity=30)
    path = "/tmp/cbu_rates.png"
    full_rgb.save(path)
    return path


def generate_forecast_image(cbu_rates):
    usd = cbu_rates.get("USD")
    if not usd:
        return None
    diff = usd["diff"]
    rate = usd["rate"]
    estimated = rate + diff
    up = diff >= 0

    top_color = (7, 92, 60) if up else (120, 14, 14)
    bottom_color = (14, 150, 95) if up else (196, 30, 30)
    width, height = 1350, 980
    canvas = vertical_gradient(width, height, top_color, bottom_color).convert("RGBA")
    canvas.alpha_composite(radial_glow(width, height, width * 0.12, height * 0.08, 480, (255, 255, 255), 40))
    canvas.alpha_composite(dot_grid(width, height, spacing=36, alpha=16))

    note_layer = Image.new("RGBA", (620, 380), (0, 0, 0, 0))
    nd = ImageDraw.Draw(note_layer)
    nd.rounded_rectangle((0, 0, 620, 380), radius=26, fill=(255, 255, 255, 26), outline=(255, 255, 255, 55), width=3)
    nd.rounded_rectangle((22, 22, 598, 358), radius=16, outline=(255, 255, 255, 40), width=2)
    nd.ellipse((260, 90, 360, 190), outline=(255, 255, 255, 50), width=3)
    df = load_font(FONT_BOLD_PATHS, 60)
    nd.text((288, 110), "$", font=df, fill=(255, 255, 255, 55))
    note_layer = note_layer.rotate(-13, expand=True, resample=Image.BICUBIC)
    canvas.paste(note_layer, (width - 560, 40), note_layer)

    draw = ImageDraw.Draw(canvas)
    flag = fetch_flag("us", 140)
    if flag:
        fmask = Image.new("L", flag.size, 0)
        ImageDraw.Draw(fmask).rounded_rectangle((0, 0, *flag.size), radius=14, fill=255)
        canvas.paste(flag, (70, 64), fmask)

    title_font = load_font(FONT_BOLD_PATHS, 52)
    draw.text((235, 70), "AQSH DOLLARI", font=title_font, fill=(255, 255, 255))
    draw.text((235, 130), "$ DOLLAR", font=title_font, fill=(255, 255, 255))

    tomorrow_str = (datetime.now(TASHKENT_TZ) + timedelta(days=1)).strftime("%d.%m.%Y")
    date_pill_font = load_font(FONT_BOLD_PATHS, 30)
    draw_pill(draw, 200, 270, f"Ertaga: {tomorrow_str}", date_pill_font, top_color, (255, 255, 255), pad_x=22, pad_y=12)

    label_font = load_font(FONT_BOLD_PATHS, 32)
    draw.text((70, 375), "KUTILAYOTGAN KURS", font=label_font, fill=(230, 230, 230))

    big_font = load_font(FONT_BOLD_PATHS, 118)
    est_text = f"{estimated:,.0f}".replace(",", " ") + " SO'M"
    soft_shadow_text(canvas, (68, 425), est_text, big_font, (255, 255, 255, 255), blur=10, offset=(0, 8), shadow_alpha=120)
    draw = ImageDraw.Draw(canvas)

    change_font = load_font(FONT_BOLD_PATHS, 40)
    arrow = "▲" if up else "▼"
    draw_pill(draw, 70 + 145, 645, f"{arrow} {diff:+.0f} so'm", change_font, top_color, (255, 255, 255), pad_x=26, pad_y=15)

    small_font = load_font(FONT_REGULAR_PATHS, 28)
    draw.text((70, 725), "Rasmiy bashorat emas — so'nggi tendensiyaga\nasoslangan taxmin", font=small_font, fill=(235, 235, 235))

    watermark_font = load_font(FONT_BOLD_PATHS, 64)
    draw.text((70, height - 130), "@BANKCHI_UZ", font=watermark_font, fill=(255, 255, 255))
    draw.text((70, height - 64), "Toshkent bank va valyuta kurslari", font=small_font, fill=(225, 225, 225))

    full_rgb = canvas.convert("RGB")
    full_rgb = add_diagonal_watermark(full_rgb, font_size=95, opacity=16)
    path = "/tmp/forecast.png"
    full_rgb.save(path)
    return path


def generate_gold_image(gold_data):
    prices = gold_data.get("prices", [])
    row_h = 130
    header_h = 220
    width = 1350
    card_pad = 32
    height = header_h + row_h * len(prices) + 110

    canvas = Image.new("RGBA", (width, height), (247, 244, 236, 255))
    header = vertical_gradient(width, header_h + 30, (150, 105, 10), (218, 168, 40)).convert("RGBA")
    header.alpha_composite(dot_grid(width, header_h + 30, spacing=30, color=(255, 255, 255), alpha=16))
    canvas.alpha_composite(header, (0, 0))
    draw = ImageDraw.Draw(canvas)

    draw_gold_bar_badge(canvas, 40, 34, 130)
    title_font = load_font(FONT_BOLD_PATHS, 50)
    sub_font = load_font(FONT_REGULAR_PATHS, 27)
    draw.text((185, 44), "OLTIN QUYMALAR NARXI", font=title_font, fill=(255, 255, 255))
    draw.text((185, 108), "Markaziy bank rasmiy narxi", font=sub_font, fill=(255, 244, 215))

    col_font = load_font(FONT_BOLD_PATHS, 26)
    y_th = header_h - 4
    draw.text((card_pad + 16, y_th), "Og'irligi", font=col_font, fill=(255, 255, 255))
    draw.text((width * 0.45, y_th), "Sotish narxi", font=col_font, fill=(255, 255, 255))
    draw.text((width * 0.72, y_th), "Qaytarib sotib olish", font=col_font, fill=(255, 255, 255))

    name_font = load_font(FONT_BOLD_PATHS, 36)
    price_font = load_font(FONT_BOLD_PATHS, 34)
    y = header_h + 34
    for item in prices:
        card_box = (card_pad, y, width - card_pad, y + row_h - 16)
        rounded_rect(draw, card_box, 20, fill=(255, 255, 255))
        draw.text((card_pad + 24, y + (row_h - 16) // 2 - 20), f"{item['gram']} gramm", font=name_font, fill=(70, 50, 15))
        sell_text = f"{item['sell']:,.0f} so'm".replace(",", " ")
        draw.text((width * 0.45, y + (row_h - 16) // 2 - 18), sell_text, font=price_font, fill=(25, 140, 70))
        buy_text = f"{item['buyback_ok']:,.0f} so'm".replace(",", " ")
        draw.text((width * 0.72, y + (row_h - 16) // 2 - 18), buy_text, font=price_font, fill=(150, 110, 40))
        y += row_h

    small_font = load_font(FONT_REGULAR_PATHS, 26)
    if gold_data.get("updated"):
        draw.text((card_pad, y + 10), f"Yangilangan: {gold_data['updated']}", font=small_font, fill=(140, 110, 50))
    draw.text((card_pad, height - 46), "@Bankchi_uz", font=small_font, fill=(140, 110, 50))

    full_rgb = canvas.convert("RGB")
    full_rgb = add_diagonal_watermark(full_rgb, font_size=115, color=(190, 150, 50), opacity=35)
    path = "/tmp/gold_prices.png"
    full_rgb.save(path)
    return path


def generate_top10_image(buy_sorted_top10):
    row_h = 118
    header_h = 230
    width = 1500
    card_pad = 32
    height = header_h + row_h * len(buy_sorted_top10) + 100

    canvas = Image.new("RGBA", (width, height), (244, 247, 251, 255))
    header = vertical_gradient(width, header_h + 30, (5, 22, 66), (18, 96, 175)).convert("RGBA")
    header.alpha_composite(radial_glow(width, header_h + 30, width * 0.85, -40, 380, (80, 190, 255), 90))
    header.alpha_composite(dot_grid(width, header_h + 30, spacing=30, alpha=14))
    canvas.alpha_composite(header, (0, 0))
    draw = ImageDraw.Draw(canvas)

    draw_money_badge(canvas, 40, 32, 110)

    title_font = load_font(FONT_BOLD_PATHS, 48)
    sub_font = load_font(FONT_REGULAR_PATHS, 26)
    draw.text((165, 34), "TOP 10 BANK", font=title_font, fill=(255, 255, 255))
    draw.text((165, 92), "$ DOLLAR eng qimmat sotib olayotgan banklar", font=sub_font, fill=(210, 232, 255))
    date_font = load_font(FONT_BOLD_PATHS, 26)
    draw_pill(draw, width - 140, 60, now_tashkent_str(), date_font, (15, 40, 90), (255, 255, 255), pad_x=18, pad_y=10)

    col_font = load_font(FONT_BOLD_PATHS, 24)
    y_th = header_h - 6
    draw.text((card_pad + 80, y_th), "Bank", font=col_font, fill=(255, 255, 255))
    draw.text((width - 560, y_th), "Sotib olish", font=col_font, fill=(255, 255, 255))
    draw.text((width - 280, y_th), "Sotish", font=col_font, fill=(255, 255, 255))

    name_font = load_font(FONT_BOLD_PATHS, 34)
    price_font = load_font(FONT_BOLD_PATHS, 34)
    y = header_h + 26
    for i, (name, buy, sell) in enumerate(buy_sorted_top10, start=1):
        card_box = (card_pad, y, width - card_pad, y + row_h - 14)
        rounded_rect(draw, card_box, 20, fill=(255, 255, 255))
        cy = y + (row_h - 14) // 2
        draw_rank_badge(draw, card_pad + 38, cy, 26, i, top3=(i <= 3))
        draw.text((card_pad + 82, cy - 22), name, font=name_font, fill=(25, 30, 48))
        buy_text = f"{buy:,.0f}".replace(",", " ")
        sell_text = f"{sell:,.0f}".replace(",", " ")
        draw.text((width - 560, cy - 20), buy_text, font=price_font, fill=(20, 140, 60))
        draw.text((width - 280, cy - 20), sell_text, font=price_font, fill=(205, 95, 20))
        y += row_h

    small_font = load_font(FONT_REGULAR_PATHS, 26)
    draw.text((card_pad, height - 52), "@Bankchi_uz", font=small_font, fill=(140, 145, 155))
    full_rgb = canvas.convert("RGB")
    full_rgb = add_diagonal_watermark(full_rgb, font_size=110, color=(160, 170, 190), opacity=32)
    path = "/tmp/top10_usd.png"
    full_rgb.save(path)
    return path


# ============================================================
#  MATNLI POSTLAR
# ============================================================

def format_buyers_post(all_rates):
    buy_sorted = sorted(all_rates.items(), key=lambda x: x[1]["buy"], reverse=True)
    lines = ["💵 <b>$ DOLLAR — eng qimmat sotib olayotgan banklar</b>"]
    lines.append(f"<i>{now_tashkent_str()} holatiga</i>")
    lines.append("<i>(dollaringizni sotmoqchi bo'lsangiz foydali)</i>\n")
    for name, r in buy_sorted:
        lines.append(f"{name}: {r['buy']:,.0f} so'm".replace(",", " "))
    lines.append(f"\n{BANK_TIP}")
    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


def format_sellers_post(all_rates):
    sell_sorted = sorted(all_rates.items(), key=lambda x: x[1]["sell"])
    lines = ["💰 <b>$ DOLLAR — eng arzon sotayotgan banklar</b>"]
    lines.append(f"<i>{now_tashkent_str()} holatiga</i>")
    lines.append("<i>(dollar sotib olmoqchi bo'lsangiz foydali)</i>\n")
    for name, r in sell_sorted:
        lines.append(f"{name}: {r['sell']:,.0f} so'm".replace(",", " "))
    lines.append(f"\n{BANK_TIP}")
    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


def format_news_post(news):
    lines = ["📰 <b>Valyuta birjasi (UzRVB) so'nggi yangiligi</b>"]
    lines.append(f"<i>{news['date']}</i>\n")
    lines.append(f"<b>{news['title']}</b>")
    lines.append(f"\n🔗 {news['url']}")
    lines.append(f"\n{CHANNEL}")
    return "\n".join(lines)


# ============================================================
#  ASOSIY DASTUR
# ============================================================

def main():
    state = load_state()
    new_state = dict(state)

    cbu_ok = True
    try:
        cbu_rates = get_cbu_rates()
        gold = get_cbu_gold()
    except Exception as e:
        print(f"CBU ma'lumotlarini olishda xatolik (o'tkazib yuborildi): {e}")
        cbu_rates = {}
        gold = {"updated": None, "prices": []}
        cbu_ok = False

    if cbu_ok:
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
    else:
        print("CBU bosqichi bu safar o'tkazib yuborildi, bank kurslariga o'tilmoqda")

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
            send_telegram_photo(top10_img, caption=f"🏆 TOP 10 bank — $ DOLLAR eng qimmat sotib olayotgan\n\n{BANK_TIP}")
        except Exception as e:
            print(f"Top10 rasm xatolik: {e}")

        new_state["banks"] = banks_key
        print("Bank reytingi (matn + rasm) yuborildi")
    else:
        print("Bank kurslari o'zgarmagan yoki mavjud emas")

    try:
        news = get_latest_uzrvb_news()
        if news and state.get("news_url") != news["url"]:
            send_telegram_message(format_news_post(news))
            new_state["news_url"] = news["url"]
            print("UzRVB yangiligi yuborildi")
        else:
            print("UzRVB yangiligi o'zgarmagan yoki topilmadi")
    except Exception as e:
        print(f"UzRVB yangiliklarini olishda xatolik (o'tkazib yuborildi): {e}")

    save_state(new_state)


if __name__ == "__main__":
    main()
