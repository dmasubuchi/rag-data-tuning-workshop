"""スキャンした書類（画像だけの PDF / PNG）を 3 点作る。

1. SCAN-MEMO-APP-0391-2ND.pdf   面接官の手書きメモ（手書き・赤ペンの丸・認印・コーヒーの染み）
2. SCAN-OFFER-APP-0386.pdf      内定承諾書（氏名の手書きと認印、会社の受付印）
3. SCAN-COVER-APP-0471.png      紹介会社の書類送付状（FAX 風。手書きの応募番号と受付印）

骨組み（3 つの関数に分け、きれいな紙を描いて劣化を足し、保存する流れ）は Qwen（qwen3-coder:30b）が書いた。
座標、折り返し、列の罫線、赤ペンの丸の描き方、PNG のメタデータの付け方は手で書き直した。
乱数は書類ごとに seed を固定している（同じ画像ができる）。

書類に書く応募番号・氏名・求人番号・段階・面接官・点数は、直書きせず scan_facts() が
台帳（source_ats.json）と評価（evaluations.json）から引く。check_all.py も同じ scan_facts() を台帳と突き合わせる。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from lib_common import DATA, NOTICE, find_font, load_json
from scan_effects import (add_coffee_ring, draw_hanko_round, draw_handwriting, draw_stamp_square,
                          save_image_pdf, scan_effect)

W, H = 1240, 1754
PAPER = (251, 250, 246)
INK = (35, 35, 35)
BLUE = (28, 40, 120)
RED_PEN = (200, 30, 30)


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    path, index = find_font(kind)
    return ImageFont.truetype(path, size, index=index)


def wrap(text: str, f: ImageFont.FreeTypeFont, max_width: float, indent: str = "") -> list[str]:
    """1 文字ずつ幅を測って折り返す（日本語向け）。2 行目以降は indent を付ける。"""
    lines, cur = [], ""
    for ch in text:
        if f.getlength(cur + ch) > max_width and cur:
            lines.append(cur)
            cur = indent + ch
        else:
            cur += ch
    lines.append(cur)
    return lines


def pen_circle(img, center, rx, ry, rng, color=RED_PEN, width=4) -> None:
    """赤ペンで囲んだ丸（少し歪み、始点と終点がずれる）。"""
    t = np.linspace(0, 2 * np.pi * 1.08, 90) + float(rng.uniform(0, 1))
    wob = 1 + rng.normal(0, 0.025, t.shape)
    pts = [(center[0] + rx * wob[i] * np.cos(a) * (1 + 0.04 * i / 90), center[1] + ry * wob[i] * np.sin(a)) for i, a in enumerate(t)]
    ImageDraw.Draw(img).line(pts, fill=color, width=width, joint="curve")


def centered(draw, xy, text, f, fill=INK):
    draw.text(xy, text, font=f, fill=fill, anchor="mt")


def notice_line(draw, y=1702):
    centered(draw, (W // 2, y), f"（{NOTICE}）", font("gothic", 22), fill=(90, 90, 90))


def scan_facts() -> dict:
    """スキャンの書類に書く事実を、台帳と評価から引いて返す（{scan の id: {...}}）。"""
    ats = load_json("source_ats.json")
    evals = {e["evaluation_id"]: e for e in load_json("evaluations.json")["rows"]}
    persons = {p["person_key"]: p["display_name"] for p in ats["persons"]}
    apps = {a["application_id"]: a for a in ats["applications"]}
    reqs = {r["req_id"]: r["title"] for r in ats["requisitions"]}
    users = {u["user_id"]: u["name"] for u in ats["users"]}
    meta = {s["id"]: s for s in load_json("scans.json")["scans"]}

    def base(sid):
        a = apps[meta[sid]["application_id"]]
        return {"id": sid, "kind": meta[sid]["kind"], "file": meta[sid]["file"], "application_id": a["application_id"], "person_key": a["person_key"],
                "candidate_name": persons[a["person_key"]], "req_id": a["req_id"], "req_title": reqs[a["req_id"]]}

    memo = base("SCAN-01")
    ev = evals[meta["SCAN-01"]["evaluation_id"]]
    held = datetime.fromisoformat(ev["held_at"])
    end = held + timedelta(hours=1)
    memo.update(evaluation_id=ev["evaluation_id"], stage=ev["stage"], interviewer=users[ev["interviewer_id"]],
                held_at=f"{held:%Y/%m/%d}　{held.hour}:{held:%M}〜{end.hour}:{end:%M}",
                overall=ev["overall"], recommendation=ev["recommendation"])

    def ymd(iso):  # "2026-10-23" -> (2026, 10, 23)
        dt = datetime.fromisoformat(iso)
        return dt.year, dt.month, dt.day

    offer = base("SCAN-02")
    wy, wm, wd = ymd(meta["SCAN-02"]["written_on"])
    ry, rm, rd = ymd(meta["SCAN-02"]["received_on"])
    offer.update(written_on=meta["SCAN-02"]["written_on"], received_on=meta["SCAN-02"]["received_on"],
                 written_text=f"{wy}年{wm}月{wd}日", received_stamp=f"{ry}.{rm:02d}.{rd:02d}")

    cover = base("SCAN-03")
    app = apps[cover["application_id"]]
    agency = next(g for g in ats["agencies"] if g["agency_id"] == app["agency_id"])
    contact = next((c["name"] for c in agency["contacts"] if c["email"] == meta["SCAN-03"]["contact_email"]), None)
    sent = datetime.fromisoformat(meta["SCAN-03"]["sent_at"])
    rec = datetime.fromisoformat(app["received_at"])
    recruiter = next((users[a["user_id"]] for a in ats["recruiter_assignments"]
                      if a["req_id"] == app["req_id"] and datetime.fromisoformat(a["assigned_from"]) <= rec
                      and (a["assigned_to"] is None or rec < datetime.fromisoformat(a["assigned_to"]))), None)
    cover.update(agency_name=agency["name"], contact_name=contact, contact_email=meta["SCAN-03"]["contact_email"],
                 sent_at=meta["SCAN-03"]["sent_at"], sent_header=f"{sent:%Y-%m-%d %H:%M}　FAX　P.1/3",
                 sent_text=f"{sent.year}年{sent.month}月{sent.day}日",
                 received_at=app["received_at"], received_stamp=f"{rec:%Y.%m.%d}", received_note=f"{rec.month}/{rec.day} 受付　{recruiter.split()[0]}",
                 recruiter=recruiter)
    return {"SCAN-01": memo, "SCAN-02": offer, "SCAN-03": cover}


def make_memo() -> None:
    """面接官の手書きメモ（印刷された様式に手書きで記入）。"""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(101)
    hp, hi = find_font("hand")
    mp, mi = find_font("mincho_bold")

    centered(d, (W // 2, 70), "面接評価メモ", font("gothic_bold", 46))
    d.line([(120, 140), (1120, 140)], fill=INK, width=2)

    # 記入欄（左: ラベル、右: 手書き）
    left, right, top, row_h, label_w = 120, 1120, 180, 64, 240
    f = scan_facts()["SCAN-01"]
    fields = [("応募番号", f["application_id"]), ("候補者名", f["candidate_name"]), ("求人番号", f["req_id"]),
              ("面接段階", f["stage"]), ("実施日時", f["held_at"]), ("面接官", f["interviewer"])]
    lab = font("gothic", 26)
    for i, (label, value) in enumerate(fields):
        y = top + i * row_h
        d.rectangle([left, y, left + label_w, y + row_h], fill=(236, 236, 232), outline=INK, width=2)
        d.rectangle([left + label_w, y, right, y + row_h], outline=INK, width=2)
        d.text((left + label_w // 2, y + row_h // 2), label, font=lab, fill=INK, anchor="mm")
        draw_handwriting(img, (left + label_w + 25, y + 12), value, hp, hi, 34, BLUE, rng)

    # メモ欄
    memo_top = top + len(fields) * row_h + 30
    memo_h = 700
    d.rectangle([left, memo_top, right, memo_top + memo_h], outline=INK, width=2)
    d.text((left + 14, memo_top + 8), "メモ", font=lab, fill=INK)
    rules = [memo_top + 76 + k * 62 for k in range(10)]
    for y in rules:
        d.line([(left + 12, y), (right - 12, y)], fill=(150, 150, 150), width=1)
    memo_items = [
        "・障害対応：月1回の夜間当番。一次切り分け→復旧まで自分で担当",
        "・AWS 本番：コンテナ基盤と RDS の構成を説明できた",
        "・設計：キュー導入の判断理由が明確。テストも書く",
        "・コードレビュー：週15件ほど。指摘の仕方も良い",
        "・懸念：特になし。入社時期は要確認",
    ]
    hand36 = ImageFont.truetype(hp, 36, index=hi)
    row = 0
    for item in memo_items:
        for line in wrap(item, hand36, 930, indent="　"):
            draw_handwriting(img, (left + 30, rules[row] - 46), line, hp, hi, 36, BLUE, rng, jitter=1.6)
            row += 1

    # 総合評価・推奨
    y1 = memo_top + memo_h + 50
    d.text((left, y1), "総合評価", font=font("gothic", 32), fill=INK)
    nums = font("gothic", 36)
    xs = [360 + k * 110 for k in range(5)]
    for k, x in enumerate(xs):
        d.text((x, y1 - 2), str(k + 1), font=nums, fill=INK)
    pen_circle(img, (xs[f["overall"] - 1] + 11, y1 + 20), 34, 30, rng)
    y2 = y1 + 90
    d.text((left, y2), "推奨", font=font("gothic", 32), fill=INK)
    opts = font("gothic", 32)
    x = 360
    for k, o in enumerate(["強く推奨", "推奨", "保留", "見送り"]):
        d.text((x, y2), o, font=opts, fill=INK)
        wd = opts.getlength(o)
        if o == f["recommendation"]:
            pen_circle(img, (x + wd / 2, y2 + 18), wd / 2 + 22, 28, rng)
        x += wd + 30
        if k < 3:
            d.text((x - 22, y2), "・", font=opts, fill=INK)
            x += 14

    # 確認印の欄
    bx0, by0 = 900, y2 + 110
    d.text((bx0 + 100, by0 - 34), "確認印", font=font("gothic", 22), fill=INK, anchor="mt")
    d.rectangle([bx0, by0, bx0 + 200, by0 + 200], outline=INK, width=2)
    draw_hanko_round(img, (bx0 + 100, by0 + 100), 70, f["interviewer"].split()[0], rng, mp, mi)
    notice_line(d)

    add_coffee_ring(img, (1010, 300), 130, rng)
    img = scan_effect(img, rng, angle=-1.8)
    save_image_pdf(img, DATA / "scans" / f["file"],
                   f"面接メモ（スキャン）{f['application_id']} {f['stage']}", NOTICE)


def make_offer() -> None:
    """内定承諾書（氏名の手書きと認印、会社の受付印）。"""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(202)
    hp, hi = find_font("hand")
    gp, gi = find_font("gothic")
    f = scan_facts()["SCAN-02"]
    mincho, mincho_b = font("mincho", 32), font("mincho_bold", 58)

    centered(d, (W // 2, 250), "内定承諾書", mincho_b)
    d.text((1120, 380), f["written_text"], font=mincho, fill=INK, anchor="rt")
    d.text((140, 450), "サンプルテック株式会社（架空の会社）　御中", font=mincho, fill=INK)
    for i, line in enumerate(wrap("　私は、貴社より内定の通知を受けた下記の職種について、これを承諾いたします。", mincho, 960)):
        d.text((140, 560 + i * 56), line, font=mincho, fill=INK)
    centered(d, (W // 2, 760), "記", font("mincho", 36))
    items = [("職種", f["req_title"]), ("求人番号", f["req_id"]),
             ("応募番号", f["application_id"]), ("入社予定日", "2026年12月1日")]
    for i, (label, value) in enumerate(items):
        y = 860 + i * 84
        d.text((200, y), label, font=mincho, fill=INK)
        d.text((500, y), value, font=mincho, fill=INK)
        d.line([(490, y + 46), (1060, y + 46)], fill=INK, width=1)
    d.text((1100, 1250), "以上", font=mincho, fill=INK, anchor="rt")
    d.text((200, 1410), "氏名", font=mincho, fill=INK)
    x_end = draw_handwriting(img, (330, 1380), f["candidate_name"], hp, hi, 58, (20, 20, 60), rng, jitter=2.5, max_rot=2.5)
    draw_hanko_round(img, (x_end + 90, 1415), 62, f["candidate_name"].split()[0], rng, *find_font("mincho_bold"))
    draw_stamp_square(img, (900, 60, 1100, 200), ["受付", f["received_stamp"], "採用担当"], rng, gp, gi)
    notice_line(d)

    img = scan_effect(img, rng, angle=1.2, noise_sigma=6.0)
    save_image_pdf(img, DATA / "scans" / f["file"], f"内定承諾書（スキャン）{f['application_id']}", NOTICE)


def make_cover() -> None:
    """紹介会社の書類送付状（FAX 風）。社内で応募番号と受付印を書き足したもの。"""
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)
    rng = np.random.default_rng(303)
    hp, hi = find_font("hand")
    gp, gi = find_font("gothic")
    f30, f32 = font("gothic", 30), font("gothic", 32)
    f = scan_facts()["SCAN-03"]

    d.text((100, 40), f["sent_header"], font=font("gothic", 20), fill=INK)
    centered(d, (480, 110), "書類送付状", font("gothic_bold", 54))
    d.text((140, 230), f["sent_text"], font=f30, fill=INK)
    d.text((140, 300), "サンプルテック株式会社（架空の会社）", font=f32, fill=INK)
    d.text((140, 350), "採用ご担当者様", font=f32, fill=INK)
    for i, line in enumerate([f["agency_name"], f"担当　{f['contact_name']}", "FAX　03-0000-0000"]):
        d.text((760, 370 + i * 50), line, font=f30, fill=INK)

    d.rectangle([140, 690, 1100, 850], outline=INK, width=2)
    centered(d, (620, 714), f"【{f['req_id']}】", font("gothic_bold", 44))
    for i, line in enumerate([f["req_title"], "候補者ご推薦の件"]):
        centered(d, (620, 774 + i * 40), line, f32)

    for i, line in enumerate(["拝啓　時下ますますご清栄のこととお慶び申し上げます。", "下記の候補者の職務経歴書を送付いたします。",
                              "ご査収のほど、よろしくお願い申し上げます。", "敬具"]):
        d.text((140, 900 + i * 60), line, font=f30, fill=INK)

    top, rh = 1180, 72
    rows = [("候補者", f["candidate_name"] + " 様"), ("送付書類", "職務経歴書　2枚"), ("送付枚数", "本状を含め 3枚")]
    for i, (label, value) in enumerate(rows):
        y = top + i * rh
        d.rectangle([140, y, 1100, y + rh], outline=INK, width=2)
        d.line([(400, y), (400, y + rh)], fill=INK, width=2)
        d.text((270, y + rh // 2), label, font=f30, fill=INK, anchor="mm")
        d.text((430, y + rh // 2), value, font=f30, fill=INK, anchor="lm")
    notice_line(d)

    # 紹介会社の社印、社内で書き足した応募番号と受付印
    draw_stamp_square(img, (950, 545, 1120, 680), [f["agency_name"], "之印"], rng, gp, gi)
    draw_handwriting(img, (880, 66), f["application_id"], hp, hi, 44, (20, 40, 150), rng)
    draw_handwriting(img, (880, 122), f["received_note"], hp, hi, 32, (20, 40, 150), rng)
    draw_stamp_square(img, (900, 180, 1110, 320), ["受付", f["received_stamp"], "採用担当"], rng, gp, gi)

    img = scan_effect(img, rng, angle=0.8, noise_sigma=8.0, blur=0.7, grayscale=True, threshold=185, quality=70)
    info = PngInfo()
    info.add_text("Title", f"書類送付状（スキャン）{f['req_id']}")
    info.add_text("Description", NOTICE)
    img.save(DATA / "scans" / f["file"], format="PNG", pnginfo=info)


def main() -> None:
    (DATA / "scans").mkdir(parents=True, exist_ok=True)
    make_memo()
    make_offer()
    make_cover()
    for facts in scan_facts().values():
        print(f"scans/{facts['file']}")


if __name__ == "__main__":
    main()
