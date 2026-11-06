"""きれいに描いた書類の画像に、紙をスキャナーで取り込んだような劣化・手書き・印鑑を足す道具。

乱数は呼び出し側から渡される numpy.random.Generator だけを使う（同じ seed なら同じ画像になる）。
"""
from __future__ import annotations

import zlib
from io import BytesIO

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

RED = (190, 30, 40)


def _font(path, index, size):
    return ImageFont.truetype(path, int(size), index=index)


def _multiply_paste(img: Image.Image, stamp: Image.Image, topleft) -> None:
    """RGBA の stamp を img に multiply 合成で重ねる（判子のように下の文字が透ける）。img を直接書き換える。"""
    x0, y0 = int(topleft[0]), int(topleft[1])
    w, h = stamp.size
    ix0, iy0 = max(x0, 0), max(y0, 0)
    ix1, iy1 = min(x0 + w, img.width), min(y0 + h, img.height)
    if ix1 <= ix0 or iy1 <= iy0:
        return
    st = np.asarray(stamp.crop((ix0 - x0, iy0 - y0, ix1 - x0, iy1 - y0)).convert("RGBA")).astype(np.float32)
    box = (ix0, iy0, ix1, iy1)
    bg = np.asarray(img.crop(box).convert("RGB")).astype(np.float32)
    a = st[..., 3:4] / 255.0
    col = st[..., :3] / 255.0
    out = bg * (1 - a) + bg * col * a
    img.paste(Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)), (ix0, iy0))


def _ink_texture(size, rng, strength=0.35):
    """判子のインクのむら（0〜1 の濃さ）。低周波のむらと細かい欠け。"""
    w, h = size
    low = rng.random((max(h // 24, 2), max(w // 24, 2)))
    low = np.asarray(Image.fromarray((low * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)).astype(np.float32) / 255.0
    fine = (rng.random((h, w)) > 0.07).astype(np.float32)
    fine = np.asarray(Image.fromarray((fine * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))).astype(np.float32) / 255.0
    return np.clip((1 - strength) + strength * low, 0, 1) * np.clip(fine * 1.15, 0, 1)


def draw_handwriting(img, xy, text, font_path, font_index, size, color, rng,
                     jitter=2.0, max_rot=3.0, spacing=1.0) -> int:
    """1 行を、1 文字ずつ位置・角度・濃さをずらして手書き風に描く。描き終わった x を返す。"""
    font = _font(font_path, font_index, size)
    x, y = xy
    pad = int(size * 0.6)
    for ch in text:
        if ch == "\n":
            continue
        w = font.getlength(ch)
        tile = Image.new("RGBA", (int(w) + 2 * pad, int(size * 2)), (0, 0, 0, 0))
        alpha = int(rng.integers(200, 256))
        ImageDraw.Draw(tile).text((pad, int(size * 0.5)), ch, font=font, fill=(*color, alpha))
        tile = tile.rotate(float(rng.uniform(-max_rot, max_rot)), resample=Image.BICUBIC, center=(pad + w / 2, size))
        dy = float(rng.uniform(-jitter, jitter))
        img.paste(tile, (int(x - pad), int(y + dy - size * 0.5)), tile)
        x += w * spacing
    return int(x)


def draw_hanko_round(img, center, radius, text, rng, font_path, font_index, color=RED) -> None:
    """丸い認印。text（1〜2 文字の姓）を縦に並べる。"""
    scale = 2
    pad = int(radius * 0.5)
    side = (radius * 2 + pad * 2) * scale
    layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = side // 2
    r = radius * scale
    d.ellipse((c - r, c - r, c + r, c + r), outline=(*color, 255), width=max(int(r * 0.09), 3))
    n = len(text)
    fsize = int(r * (1.45 if n == 1 else 0.98))
    font = _font(font_path, font_index, fsize)
    total = fsize * n
    for i, ch in enumerate(text):
        w = font.getlength(ch)
        d.text((c - w / 2, c - total / 2 + i * fsize - fsize * 0.06), ch, font=font, fill=(*color, 255))
    layer = layer.resize((side // scale, side // scale), Image.LANCZOS)
    arr = np.asarray(layer).astype(np.float32)
    arr[..., 3] *= _ink_texture(layer.size, rng)
    layer = Image.fromarray(arr.astype(np.uint8), "RGBA")
    layer = layer.rotate(float(rng.uniform(-8, 8)), resample=Image.BICUBIC)
    _multiply_paste(img, layer, (center[0] - layer.width // 2, center[1] - layer.height // 2))


def draw_stamp_square(img, rect, lines, rng, font_path, font_index, color=RED) -> None:
    """四角い受付印・社印。rect=(x0, y0, x1, y1) の枠の中に lines を中央寄せで並べる。"""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    pad = 20
    layer = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle((pad, pad, pad + w, pad + h), outline=(*color, 255), width=4)
    size = 80
    while size > 12:
        font = _font(font_path, font_index, size)
        widest = max(font.getlength(s) for s in lines)
        if widest <= w * 0.82 and size * 1.2 * len(lines) <= h * 0.88:
            break
        size -= 2
    font = _font(font_path, font_index, size)
    line_h = h / len(lines)
    for i, s in enumerate(lines):
        tw = font.getlength(s)
        d.text((pad + (w - tw) / 2, pad + i * line_h + (line_h - size) / 2 - size * 0.08), s, font=font, fill=(*color, 255))
    arr = np.asarray(layer).astype(np.float32)
    arr[..., 3] *= _ink_texture(layer.size, rng, strength=0.45)
    layer = Image.fromarray(arr.astype(np.uint8), "RGBA").rotate(float(rng.uniform(-4, 4)), resample=Image.BICUBIC)
    _multiply_paste(img, layer, (x0 - pad, y0 - pad))


def add_coffee_ring(img, center, radius, rng) -> None:
    """コーヒーカップの輪染み（茶色の薄い輪。一部が欠ける）。"""
    pad = 40
    side = (radius + pad) * 2
    layer = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = side // 2
    start = float(rng.uniform(0, 360))
    for width, alpha, dr in ((int(rng.integers(6, 9)), 95, 0), (3, 55, 7)):
        rr = radius + dr
        d.arc((c - rr, c - rr, c + rr, c + rr), start, start + float(rng.uniform(280, 330)),
              fill=(150, 110, 60, alpha), width=width)
    d.ellipse((c - radius + 6, c - radius + 6, c + radius - 6, c + radius - 6), fill=(150, 110, 60, 6))
    layer = layer.filter(ImageFilter.GaussianBlur(2.2))
    _multiply_paste(img, layer, (center[0] - side // 2, center[1] - side // 2))


def scan_effect(img, rng, angle=-1.5, background=(232, 232, 230), shadow=True, noise_sigma=7.0,
                dust=250, blur=0.7, quality=72, grayscale=False, threshold=None):
    """紙を少し傾け、明るさのむら・ノイズ・ゴミ・折り目・ぼかし・JPEG の劣化を足す。"""
    img = img.convert("RGB")
    w, h = img.size
    # (a) 傾けて、紙の外側（スキャナーの地）を埋める。紙の端に影。
    paper = img.rotate(angle, resample=Image.BICUBIC, fillcolor=tuple(background))
    mask = Image.new("L", (w, h), 255).rotate(angle, resample=Image.BICUBIC, fillcolor=0)
    arr = np.asarray(paper).astype(np.float32)
    if shadow:
        sh = ImageChops.offset(mask, 7, 7).filter(ImageFilter.GaussianBlur(7))
        only = np.clip(np.asarray(sh).astype(np.float32) - np.asarray(mask).astype(np.float32), 0, 255) / 255.0
        arr *= (1 - 0.35 * only)[..., None]
    # (b) 明るさのむら（左上が明るく、右下が暗い）
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    arr *= (1.0 - 0.06 * (0.5 * xx / w + 0.5 * yy / h))[..., None]
    # (c) ノイズ
    arr += rng.normal(0, noise_sigma, (h, w)).astype(np.float32)[..., None]
    arr += rng.normal(0, noise_sigma * 0.3, (h, w, 3)).astype(np.float32)
    # (e) 折り目（縦の 1/3 あたりの横線）
    fold = h // 3 + int(rng.integers(-25, 25))
    prof = -0.05 * np.exp(-((yy[:, 0] - fold) / 2.5) ** 2) + 0.035 * np.exp(-((yy[:, 0] - fold - 5) / 2.5) ** 2)
    arr *= (1 + prof)[:, None, None]
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    # (d) ゴミ
    d = ImageDraw.Draw(out)
    for _ in range(int(dust)):
        x, y = int(rng.integers(0, w - 4)), int(rng.integers(0, h - 4))
        r = int(rng.integers(1, 4))
        v = int(rng.integers(70, 160))
        d.ellipse((x, y, x + r, y + r), fill=(v, v, v))
    # (f) ぼかし
    out = out.filter(ImageFilter.GaussianBlur(blur))
    # (g) グレースケール・二値化（FAX 風）
    if grayscale:
        out = out.convert("L")
        if threshold is not None:
            a = np.asarray(out)
            a = np.where(a < threshold, 0, 255).astype(np.uint8)
            for _ in range(int(rng.integers(3, 6))):          # FAX の横スジ
                y = int(rng.integers(0, h - 3))
                t = int(rng.integers(1, 3))
                a[y:y + t, :] = np.where(rng.random(w) > 0.5, 0, 255).astype(np.uint8)[None, :]
            out = Image.fromarray(a, "L")
    # (h) JPEG の劣化
    buf = BytesIO()
    out.save(buf, format="JPEG", quality=int(quality))
    buf.seek(0)
    out = Image.open(buf)
    out.load()
    return out


def save_image_pdf(img, path, title, subject, quality=80) -> None:
    """画像だけの PDF（文字のレイヤーなし）。日時を入れず、同じ画像から同じバイト列になるように自前で書く。"""
    gray = img.mode == "L"
    buf = BytesIO()
    img.convert("L" if gray else "RGB").save(buf, format="JPEG", quality=quality)
    jpeg = buf.getvalue()
    w, h = img.size
    pw, ph = w * 72.0 / 150.0, h * 72.0 / 150.0

    def u16(s: str) -> str:
        return "<FEFF" + s.encode("utf-16-be").hex().upper() + ">"

    content = f"q {pw:.2f} 0 0 {ph:.2f} 0 0 cm /Im0 Do Q".encode("ascii")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw:.2f} {ph:.2f}] /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>".encode(),
        (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /{'DeviceGray' if gray else 'DeviceRGB'} "
         f"/BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg)} >>").encode(),
        f"<< /Length {len(content)} >>".encode(),
        f"<< /Title {u16(title)} /Subject {u16(subject)} /Creator {u16('サンプルテック 採用（研修用）')} >>".encode(),
    ]
    streams = {4: jpeg, 5: content}
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body
        if i in streams:
            out += b"\nstream\n" + streams[i] + b"\nendstream"
        out += b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for o in offsets:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    with open(path, "wb") as f:
        f.write(bytes(out))
