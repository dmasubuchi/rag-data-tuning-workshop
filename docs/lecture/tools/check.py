#!/usr/bin/env python3
"""site/lecture/ のデッキを Playwright で開き、全スライドの静止画と、はみ出し・JS のエラーを調べる。

実行（Repo の直下で）：python3 docs/lecture/tools/check.py [--out <静止画の置き場>] [--site <調べるフォルダー>] [--decks <decks の JSON>] [デッキの id …]
- --site と --decks を省くと、site/lecture と docs/lecture/decks.json を調べる
- 要るもの：playwright と Chromium（作る人の道具）。一覧の画像（contact.png）は ffmpeg があるときだけ作る
- 静止画は --out（既定は OS の一時フォルダーの lecture-check/）に、デッキごとに 01_<id>.png … と contact.png（一覧）を作る。Repo には置かない
- はみ出し（kw の段が 18px まで縮めても収まらない、など）と JS のエラーを画面に出す。終了コードは、JS のエラーがあれば 1
- プレイヤーの操作も1つずつ確かめる（目次が開く、→ キーで進む、N でノートが出る）
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
OUT_SITE = REPO / "site" / "lecture"

OVERFLOW_JS = r"""
() => {
  const stage = document.getElementById('stage');
  const out = [];
  const hidden = el => { for (let e = el; e && e !== stage; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.visibility === 'hidden' || cs.display === 'none') return true; } return false; };
  const name = el => el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).join('.') : '');
  const main = stage.querySelector('main');
  stage.querySelectorAll('*').forEach(el => {
    if (el.closest('svg') || hidden(el)) return;
    const cs = getComputedStyle(el);
    const clip = cs.overflow === 'hidden' || cs.overflowX === 'hidden' || cs.overflowY === 'hidden';
    if (clip && el.clientWidth > 0 && (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1))
      out.push(`${name(el)} の中身が枠から出ている（${el.scrollWidth}x${el.scrollHeight} > ${el.clientWidth}x${el.clientHeight}）`);
    if (main && main.contains(el) && el !== main) {
      const r = el.getBoundingClientRect(), mr = main.getBoundingClientRect();
      if (r.width > 0 && (r.bottom > mr.bottom + 1 || r.right > mr.right + 1)) out.push(`${name(el)} が本文の領域の外へ出ている`);
    }
  });
  const fit = stage.querySelector('.kfit');
  const fs = fit ? parseInt(fit.style.fontSize, 10) : null;
  return {msgs: [...new Set(out)].slice(0, 4), fs};
}
"""


def check_deck(p, deck_id: str, out: Path) -> tuple[list[str], list[str]]:
    html = OUT_SITE / deck_id / "slides.html"
    cd = out / deck_id
    cd.mkdir(parents=True, exist_ok=True)
    for old in cd.glob("*.png"):
        old.unlink()
    errors: list[str] = []
    notes: list[str] = []
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    pg.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    pg.goto(html.as_uri() + "?render")
    info = pg.evaluate("deckInfo()")
    for i, s in enumerate(info):
        pg.evaluate("([i, st]) => renderSlide(i, st)", [i, s["steps"]])
        pg.wait_for_function("() => [...document.querySelectorAll('#stage img')].every(im => im.complete)")
        pg.screenshot(path=str(cd / f"{i + 1:02d}_{s['id']}.png"))
        r = pg.evaluate(OVERFLOW_JS)
        for msg in r["msgs"]:
            notes.append(f"{deck_id} #{i + 1} {s['id']}：はみ出しの疑い：{msg}")
        if r["fs"] is not None and r["fs"] <= 18:
            notes.append(f"{deck_id} #{i + 1} {s['id']}：本文を {r['fs']}px まで縮めた（文字が多い）")
    b.close()
    n = len(info)
    rows = (n + 3) // 4
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-pattern_type", "glob", "-i", str(cd / "[0-9]*.png"),
                    "-vf", f"scale=640:-1,tile=4x{rows}:padding=8:color=white", "-frames:v", "1", str(cd / "contact.png")], check=True)
    return errors, notes


def check_player(p, out: Path) -> list[str]:
    """プレイヤーとして開いたときの操作：目次のカード、→ で進む、N でノート"""
    errors: list[str] = []
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1600, "height": 900})
    pg.on("pageerror", lambda e: errors.append(f"player pageerror: {e}"))
    pg.goto((OUT_SITE / "index.html").as_uri())
    pg.wait_for_selector(".sp-card")
    n_cards = pg.locator(".sp-card").count()
    pg.screenshot(path=str(out / "player-index.png"))
    pg.goto((OUT_SITE / "part1-search" / "slides.html").as_uri())
    pg.wait_for_timeout(800)
    pg.keyboard.press("ArrowRight")
    pg.wait_for_timeout(600)
    pg.keyboard.press("ArrowRight")
    pg.wait_for_timeout(600)
    h = pg.evaluate("location.hash")
    pg.screenshot(path=str(out / "player-part1-step.png"))
    pg.keyboard.press("n")
    pg.wait_for_timeout(600)
    pg.screenshot(path=str(out / "player-part1-notes.png"))
    b.close()
    print(f"プレイヤー：目次のカード {n_cards} 枚、→ を2回押したあとの位置 {h}")
    return errors


def main(argv: list[str]) -> int:
    from playwright.sync_api import sync_playwright
    global OUT_SITE
    opts = {"--out", "--site", "--decks"}
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else Path(tempfile.gettempdir()) / "lecture-check"
    if "--site" in argv:        # 調べるフォルダー（既定は site/lecture）。短縮版は --site site/lecture-short
        OUT_SITE = Path(argv[argv.index("--site") + 1]).resolve()
    decks_path = Path(argv[argv.index("--decks") + 1]).resolve() if "--decks" in argv else HERE.parent / "decks.json"
    ids = [a for k, a in enumerate(argv) if not a.startswith("--") and (k == 0 or argv[k - 1] not in opts)]
    conf = json.loads(decks_path.read_text(encoding="utf-8"))
    ids = ids or [d["id"] for d in conf["decks"]]
    out.mkdir(parents=True, exist_ok=True)
    all_err: list[str] = []
    all_notes: list[str] = []
    with sync_playwright() as p:
        for d in ids:
            e, n = check_deck(p, d, out)
            all_err += e
            all_notes += n
            print(f"{d}：静止画 {out / d}")
        all_err += check_player(p, out)
    for n in all_notes:
        print("注意：", n)
    for e in all_err:
        print("エラー：", e)
    print(f"注意 {len(all_notes)} 件、エラー {len(all_err)} 件。一覧は {out}/<デッキ>/contact.png")
    return 1 if all_err else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
