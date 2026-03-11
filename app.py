from flask import Flask, request, jsonify, send_file
import requests
import io
import base64
import textwrap
from PIL import Image, ImageDraw, ImageFont
import os
import traceback

app = Flask(__name__)

CANVAS_W, CANVAS_H = 1080, 1350

GRID_10 = [
    (45,155),(565,155),
    (45,385),(565,385),
    (45,615),(565,615),
    (45,845),(565,845),
    (45,1075),(565,1075),
]
GRID_8 = [
    (45,175),(565,175),
    (45,460),(565,460),
    (45,745),(565,745),
    (45,1030),(565,1030),
]
COL_CENTERS = [270, 810]
PHOTO_W, PHOTO_H = 460, 210

COLOR_PRICE_NEW = (180, 30, 30)
COLOR_PRICE_OLD = (120, 120, 120)
COLOR_NAME = (30, 30, 30)
COLOR_BADGE_BG = (80, 170, 60)
COLOR_BADGE_TEXT = (255, 255, 255)
COLOR_DATE = (80, 80, 80)
COLOR_UNIT = (60, 60, 60)

def download_drive_file(file_id, access_token):
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return io.BytesIO(r.content)

def draw_multiline_centered(draw, text, cx, y, font, color, max_width, line_spacing=4):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0,0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    line_h = draw.textbbox((0,0), "Ag", font=font)[3] + line_spacing
    ty = y
    for line in lines:
        bbox = draw.textbbox((0,0), line, font=font)
        tx = cx - (bbox[2] - bbox[0]) // 2
        draw.text((tx, ty), line, font=font, fill=color)
        ty += line_h
    return line_h * len(lines)

def draw_discount_badge(draw, cx, y, discount_text, font_badge):
    rx, ry = 38, 22
    draw.ellipse([(cx-rx, y-ry), (cx+rx, y+ry)], fill=COLOR_BADGE_BG)
    bbox = draw.textbbox((0,0), discount_text, font=font_badge)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw//2, y - th//2 - 2), discount_text, font=font_badge, fill=COLOR_BADGE_TEXT)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json()
        access_token = data.get('access_token')
        template_id = data.get('template_id')
        font_id = data.get('font_id')
        articles = data.get('articles', [])
        image_map = data.get('image_map', {})
        date_range = data.get('date_range', '')
        filename = data.get('filename', 'poster.jpg')

        tmpl_buf = download_drive_file(template_id, access_token)
        canvas = Image.open(tmpl_buf).convert("RGBA")
        canvas = canvas.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)

        font_buf = download_drive_file(font_id, access_token)
        font_data_bytes = font_buf.read()

        def make_font(size):
            return ImageFont.truetype(io.BytesIO(font_data_bytes), size)

        font_name = make_font(17)
        font_price_big = make_font(52)
        font_price_old = make_font(20)
        font_unit = make_font(13)
        font_badge = make_font(16)
        font_date = make_font(22)

        draw = ImageDraw.Draw(canvas)

        if date_range:
            bbox = draw.textbbox((0,0), date_range, font=font_date)
            tw = bbox[2] - bbox[0]
            draw.text((CANVAS_W//2 - tw//2, 148), date_range, font=font_date, fill=COLOR_DATE)

        grid = GRID_10 if len(articles) >= 9 else GRID_8
        col_w = 480

        for i, art in enumerate(articles):
            if i >= len(grid):
                break
            gx, gy = grid[i]
            col = i % 2
            cx = COL_CENTERS[col]

            art_id = str(art.get('articul', ''))
            name = str(art.get('name', '')).upper()
            price_new = art.get('price_new', '')
            price_old = art.get('price_old', '')
            discount = art.get('discount', '')
            unit = art.get('unit', 'ГРН/КГ').upper()

            photo_img = None
            drive_id = image_map.get(art_id)
            if drive_id:
                try:
                    photo_buf = download_drive_file(drive_id, access_token)
                    photo_img = Image.open(photo_buf).convert("RGBA")
                    ph = int(PHOTO_W * photo_img.height / photo_img.width)
                    if ph > PHOTO_H:
                        pw = int(PHOTO_H * photo_img.width / photo_img.height)
                        ph = PHOTO_H
                    else:
                        pw = PHOTO_W
                    photo_img = photo_img.resize((pw, ph), Image.LANCZOS)
                except Exception:
                    photo_img = None

            draw_multiline_centered(draw, name, cx, gy, font_name, COLOR_NAME, col_w - 10)

            if photo_img:
                px = cx - photo_img.width // 2
                py = gy + 38
                canvas.paste(photo_img, (px, py), photo_img)
                photo_bottom = py + photo_img.height
            else:
                photo_bottom = gy + PHOTO_H + 38

            if discount:
                badge_text = f"-{discount}%"
                badge_cx = cx + PHOTO_W // 2 - 48
                badge_cy = gy + 38 + (photo_img.height if photo_img else PHOTO_H) - 22
                draw_discount_badge(draw, badge_cx, badge_cy, badge_text, font_badge)

            price_y = photo_bottom + 6
            p_new_str = str(price_new)
            p_old_str = str(price_old)

            bbox_new = draw.textbbox((0,0), p_new_str, font=font_price_big)
            new_w = bbox_new[2] - bbox_new[0]
            bbox_unit = draw.textbbox((0,0), unit, font=font_unit)
            unit_w = bbox_unit[2] - bbox_unit[0]
            bbox_old = draw.textbbox((0,0), p_old_str, font=font_price_old)
            old_w = bbox_old[2] - bbox_old[0]

            total_price_w = new_w + 6 + max(unit_w, old_w)
            start_x = cx - total_price_w // 2

            draw.text((start_x, price_y), p_new_str, font=font_price_big, fill=COLOR_PRICE_NEW)
            draw.text((start_x + new_w + 4, price_y + 4), unit, font=font_unit, fill=COLOR_UNIT)
            oy = price_y + 20
            draw.text((start_x + new_w + 4, oy), p_old_str, font=font_price_old, fill=COLOR_PRICE_OLD)
            ob = draw.textbbox((start_x + new_w + 4, oy), p_old_str, font=font_price_old)
            mid_y = (ob[1] + ob[3]) // 2
            draw.line([(ob[0], mid_y), (ob[2], mid_y)], fill=COLOR_PRICE_OLD, width=2)

        output = canvas.convert("RGB")
        buf = io.BytesIO()
        output.save(buf, format="JPEG", quality=92)
        buf.seek(0)

        return send_file(buf, mimetype='image/jpeg', as_attachment=True, download_name=filename)

    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
