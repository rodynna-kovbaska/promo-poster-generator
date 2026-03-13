from flask import Flask, request, jsonify, send_file
import io
import base64
import traceback
from PIL import Image, ImageDraw, ImageFont
import os

app = Flask(__name__)

CANVAS_W, CANVAS_H = 1080, 1350

# Grid positions: top-left corner (x, y) of each cell, for 10 and 8 articles
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
PHOTO_W, PHOTO_H = 460, 250   # photo area per cell

COLOR_PRICE_NEW  = (180, 30, 30)
COLOR_PRICE_OLD  = (120, 120, 120)
COLOR_NAME       = (30, 30, 30)
COLOR_BADGE_BG   = (80, 170, 60)
COLOR_BADGE_TEXT = (255, 255, 255)
COLOR_DATE       = (80, 80, 80)
COLOR_UNIT       = (60, 60, 60)


def b64_to_buf(b64str):
    raw = base64.b64decode(b64str)
    return io.BytesIO(raw)


def draw_multiline_centered(draw, text, cx, y, font, color, max_width, line_spacing=4):
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    line_h = draw.textbbox((0, 0), "Ag", font=font)[3] + line_spacing
    ty = y
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        tx = cx - (bbox[2] - bbox[0]) // 2
        draw.text((tx, ty), line, font=font, fill=color)
        ty += line_h
    return line_h * len(lines)


def draw_discount_badge(draw, cx, y, discount_text, font_badge):
    # Round badge (equal rx and ry)
    r = 24
    draw.ellipse([(cx - r, y - r), (cx + r, y + r)], fill=COLOR_BADGE_BG)
    bbox = draw.textbbox((0, 0), discount_text, font=font_badge)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw // 2, y - th // 2 - 1), discount_text, font=font_badge, fill=COLOR_BADGE_TEXT)


def lookup_photo(image_map_b64, art_id):
    """Try several key variants to find photo in image_map."""
    candidates = [
        art_id,                          # exact: "20137"
        art_id.lstrip('0'),              # strip leading zeros: "20137" -> "20137"
        str(int(art_id)) if art_id.isdigit() else art_id,  # int conversion
    ]
    # Also try removing first digit if 5+ chars
    if len(art_id) >= 5 and art_id.isdigit():
        candidates.append(art_id[1:])   # "20137" -> "0137" and then stripped
        candidates.append(art_id[1:].lstrip('0'))  # "20137" -> "137"... wait
        # Actually "20137" -> art_id[1:] = "0137", lstrip = "137"? No: "2137"
        # Let's try: remove leading "2" if number starts with "2" and length 5
        candidates.append(art_id.lstrip('2'))  # remove leading 2 -> "0137"
    for key in candidates:
        if key in image_map_b64:
            return image_map_b64[key]
    return None


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"})


@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json(force=True)

        template_b64 = data.get('template_b64', '')
        font_b64     = data.get('font_b64', '')
        articles     = data.get('articles', [])
        image_map_b64 = data.get('image_map_b64', {})
        date_range   = data.get('date_range', '')
        filename     = data.get('filename', 'poster.jpg')

        if not template_b64:
            return jsonify({"error": "template_b64 is required"}), 400
        if not font_b64:
            return jsonify({"error": "font_b64 is required"}), 400

        # Load template
        tmpl_buf = b64_to_buf(template_b64)
        canvas = Image.open(tmpl_buf).convert("RGBA")
        canvas = canvas.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)

        # Load font bytes once
        font_data_bytes = base64.b64decode(font_b64)
        def make_font(size):
            return ImageFont.truetype(io.BytesIO(font_data_bytes), size)

        font_name      = make_font(17)
        font_price_big = make_font(56)
        font_price_old = make_font(20)
        font_unit      = make_font(13)
        font_badge     = make_font(15)
        font_date      = make_font(22)

        draw = ImageDraw.Draw(canvas)

        # Date range header
        if date_range:
            bbox = draw.textbbox((0, 0), date_range, font=font_date)
            tw = bbox[2] - bbox[0]
            draw.text((CANVAS_W // 2 - tw // 2, 148), date_range, font=font_date, fill=COLOR_DATE)

        grid  = GRID_10 if len(articles) >= 9 else GRID_8
        col_w = 480

        for i, art in enumerate(articles):
            if i >= len(grid):
                break

            gx, gy = grid[i]
            col    = i % 2
            cx     = COL_CENTERS[col]

            art_id    = str(art.get('articul', ''))
            name      = str(art.get('name', '')).upper()
            price_new = str(art.get('price_new', ''))
            price_old = str(art.get('price_old', ''))
            discount  = str(art.get('discount', ''))
            unit      = str(art.get('unit', 'ГРН/КГ')).upper()

            # --- Product photo ---
            photo_img = None
            photo_b64 = lookup_photo(image_map_b64, art_id)
            if photo_b64:
                try:
                    photo_buf = b64_to_buf(photo_b64)
                    raw_img   = Image.open(photo_buf).convert("RGBA")
                    # Fit into PHOTO_W x PHOTO_H keeping aspect ratio
                    ratio = min(PHOTO_W / raw_img.width, PHOTO_H / raw_img.height)
                    pw    = int(raw_img.width  * ratio)
                    ph    = int(raw_img.height * ratio)
                    photo_img = raw_img.resize((pw, ph), Image.LANCZOS)
                except Exception:
                    photo_img = None

            # --- Draw product name (above photo) ---
            draw_multiline_centered(draw, name, cx, gy, font_name, COLOR_NAME, col_w - 10)

            # --- Paste photo ---
            photo_top = gy + 38
            if photo_img:
                px = cx - photo_img.width  // 2
                py = photo_top
                canvas.paste(photo_img, (px, py), photo_img)
                photo_bottom = py + photo_img.height
            else:
                photo_bottom = photo_top + PHOTO_H

            # --- Discount badge (round, bottom-right of photo) ---
            if discount and discount != '0':
                try:
                    disc_pct   = round(abs(float(discount)) * 100)
                    badge_text = "-" + str(disc_pct) + "%"
                except Exception:
                    badge_text = "-" + discount + "%"
                badge_cx = cx + PHOTO_W // 2 - 30
                badge_cy = photo_bottom - 28
                draw_discount_badge(draw, badge_cx, badge_cy, badge_text, font_badge)

            # --- Prices ---
            price_y = photo_bottom + 8

            bbox_new  = draw.textbbox((0, 0), price_new, font=font_price_big)
            new_w     = bbox_new[2] - bbox_new[0]
            bbox_unit = draw.textbbox((0, 0), unit, font=font_unit)
            unit_w    = bbox_unit[2] - bbox_unit[0]
            bbox_old  = draw.textbbox((0, 0), price_old, font=font_price_old)
            old_w     = bbox_old[2] - bbox_old[0]

            total_price_w = new_w + 6 + max(unit_w, old_w)
            start_x       = cx - total_price_w // 2

            draw.text((start_x, price_y), price_new, font=font_price_big, fill=COLOR_PRICE_NEW)
            draw.text((start_x + new_w + 4, price_y + 4), unit, font=font_unit, fill=COLOR_UNIT)

            oy = price_y + 22
            draw.text((start_x + new_w + 4, oy), price_old, font=font_price_old, fill=COLOR_PRICE_OLD)
            ob  = draw.textbbox((start_x + new_w + 4, oy), price_old, font=font_price_old)
            mid = (ob[1] + ob[3]) // 2
            draw.line([(ob[0], mid), (ob[2], mid)], fill=COLOR_PRICE_OLD, width=2)

        # Save as JPEG
        output = canvas.convert("RGB")
        buf    = io.BytesIO()
        output.save(buf, format="JPEG", quality=92)
        buf.seek(0)
        return send_file(buf, mimetype='image/jpeg', as_attachment=True, download_name=filename)

    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
