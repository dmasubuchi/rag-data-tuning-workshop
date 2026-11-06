"""検査（check_all.py / check_identity.py）が本当に誤りを見つけるかの自己試験。

applied/data を一時フォルダーに複製し、既知の誤り（実際に起きた MAIL-09/10 の本文の入れ替えを含む）を 1 つずつ入れて
作り直し、検査が NG にすることを確かめる。元のファイルは変えない。見逃しがあれば 1 を返す。

禁止語（固有名）の検査は、本物の一覧を使わない。この試験が一時のファイルに作る、架空の語の一覧を、環境変数
PUBLIC_CHECK_BANNED で check_all.py に渡す（一覧がないときに 2 で止まることも確かめる）。

    python _build/selftest_check.py          # 全部
    python _build/selftest_check.py 1 15     # 番号を指定
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
PY = sys.executable
WORK = Path(tempfile.mkdtemp(prefix="applied-selftest-"))
FAKE_WORDS = ["ファントム商事", "PHANTOMCORP"]          # 架空の禁止語。本物の一覧ではない
BANNED_FILE = WORK / "banned-fake.txt"
BANNED_FILE.parent.mkdir(parents=True, exist_ok=True)
BANNED_FILE.write_text("\n".join(FAKE_WORDS) + "\n", encoding="utf-8")
ENV = {**os.environ, "PUBLIC_CHECK_BANNED": str(BANNED_FILE)}
def jedit(path, fn):
    d = json.load(open(path, encoding="utf-8")); fn(d); json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def mail(root, i, fn):
    jedit(root/"_build/content/mail.json", lambda d: fn(next(m for m in d["mails"] if m["id"] == i)))
def evl(root, i, fn):
    jedit(root/"_build/content/evaluations.json", lambda d: fn(next(r for r in d["rows"] if r["evaluation_id"] == i)))
def scan(root, i, fn):
    jedit(root/"_build/content/scans.json", lambda d: fn(next(r for r in d["scans"] if r["id"] == i)))
def sub(path, a, b):
    t = Path(path).read_text(encoding="utf-8"); assert a in t, a; Path(path).write_text(t.replace(a, b, 1), encoding="utf-8")
def swap_bodies(root):
    def f(d):
        x = {m["id"]: m for m in d["mails"]}; x["MAIL-09"]["body"], x["MAIL-10"]["body"] = x["MAIL-10"]["body"], x["MAIL-09"]["body"]
    jedit(root/"_build/content/mail.json", f)
def append_body(root, i, s_):
    mail(root, i, lambda m: m.__setitem__("body", m["body"].replace("\n\n"+m["from"]["name"], "\n"+s_+"\n\n"+m["from"]["name"])))
tests = {
 "1 MAIL-09/10 の本文入れ替え（実際の誤り）": swap_bodies,
 "2 MAIL-05 の本文に別の人の氏名": lambda r: sub(r/"_build/content/mail.json", "市川 浩二様（応募番号 APP-0391", "田村 朋美様（応募番号 APP-0391"),
 "3 MAIL-07 の宛先が別の紹介会社": lambda r: mail(r, "MAIL-07", lambda m: m.__setitem__("to", [{"name": "松田 恵", "email": "megumi.matsuda@gamma.example"}])),
 "4 MAIL-04 に内定の文言": lambda r: append_body(r, "MAIL-04", "内定が決まりました。"),
 "5 MAIL-06 の本文の応募番号が別": lambda r: sub(r/"_build/content/mail.json", "市川 浩二様（応募番号 APP-0391）の二", "市川 浩二様（応募番号 APP-0392）の二"),
 "6 経歴書 0392 の氏名が別の人": lambda r: sub(r/"_build/content/resumes/CV-APP-0392.md", "氏名: 田村 朋美", "氏名: 市川 浩二"),
 "7 経歴書 0386 の求人番号が別": lambda r: sub(r/"_build/content/resumes/CV-APP-0386.md", "応募求人: REQ-043", "応募求人: REQ-042"),
 "8 評価 EV-005 の応募番号が別": lambda r: evl(r, "EV-005", lambda e: e.__setitem__("application_id", "APP-0391")),
 "9 評価 EV-003 の点数と推奨が対応しない": lambda r: evl(r, "EV-003", lambda e: e.__setitem__("overall", 3)),
 "10 評価 EV-012 の文章に別の人の氏名": lambda r: evl(r, "EV-012", lambda e: e.__setitem__("comment", "市川 浩二と同様に強く推奨する。")),
 "11 内定承諾書が内定していない応募": lambda r: scan(r, "SCAN-02", lambda s_: s_.__setitem__("application_id", "APP-0391")),
 "12 送付状の担当者が別の紹介会社": lambda r: scan(r, "SCAN-03", lambda s_: s_.__setitem__("contact_email", "yuki.kamei@alpha.example")),
 "13 求人票の求人番号が別": lambda r: sub(r/"_build/content/jobs/JOB-REQ043-v1.md", "求人番号: REQ-043", "求人番号: REQ-044"),
 "14 files.json の経歴書の人物キーが別": lambda r: jedit(r/"_build/content/files.json", lambda d: next(f for f in d["files"] if f["path"].endswith("CV-APP-0391.docx")).__setitem__("person_keys", ["C-121"])),
 "15 MAIL-01 の曜日が違う": lambda r: sub(r/"_build/content/mail.json", "・10月21日（水）14時\\n・10月22日（木）10時", "・10月21日（火）14時\\n・10月22日（木）10時"),
 "16 MAIL-06 の担当者が交代前の人": lambda r: mail(r, "MAIL-06", lambda m: m.__setitem__("from", {"name": "山本 花子", "email": "hanako.yamamoto@sampletech.example"})),
 "17 MAIL-03 の提出時刻が評価と違う": lambda r: sub(r/"_build/content/mail.json", "17時30分に提出", "17時40分に提出"),
 "18 経歴書 0471 の作成日が受付日と違う": lambda r: sub(r/"_build/content/resumes/CV-APP-0471.md", "作成日: 2026年10月28日", "作成日: 2026年10月27日"),
 "20 旧い版の求人票の求人番号が別": lambda r: sub(r/"_build/content/updates/JOB-REQ042-v1.md", "求人番号: REQ-042", "求人番号: REQ-043"),
 "21 旧い版の求人票の有効開始が台帳と違う": lambda r: sub(r/"_build/content/updates/JOB-REQ042-v1.md", "有効開始: 2026年9月1日", "有効開始: 2026年9月2日"),
 "22 旧い版の求人票に応募者の名前": lambda r: sub(r/"_build/content/updates/JOB-REQ042-v1.md", "段階的に新しい機能の設計を任せていきます。", "段階的に新しい機能の設計を任せていきます。市川 浩二様の応募を受けています。"),
 "23 旧い版の求人票が現行の版と同じ版": lambda r: sub(r/"_build/content/updates/JOB-REQ042-v1.md", "版: v1", "版: v3"),
 "19 評価 EV-011 の提出が面接の前日": lambda r: evl(r, "EV-011", lambda e: e.__setitem__("submitted_at", "2026-10-06 12:10")),
 "24 求人票に禁止語（架空）": lambda r: sub(r/"_build/content/jobs/JOB-REQ043-v1.md", "求人番号: REQ-043", "求人番号: REQ-043\n運営: ファントム商事"),
 "25 経歴書に禁止語（架空。全角の英字）": lambda r: sub(r/"_build/content/resumes/CV-APP-0386.md", "応募求人: REQ-043", "応募求人: REQ-043\n前職: ＰＨＡＮＴＯＭＣＯＲＰ"),
 "26 メールが予約済みでないドメイン": lambda r: mail(r, "MAIL-07", lambda m: m.__setitem__("to", [{"name": "松田 恵", "email": "megumi.matsuda" + "@" + "gamma.corp-mail.org"}])),
}
only = sys.argv[1:] 
bad_pass = 0
for name, mut in tests.items():
    if only and name.split()[0] not in only: continue
    root = WORK/name.split()[0]; shutil.rmtree(root, ignore_errors=True); shutil.copytree(SRC, root, ignore=shutil.ignore_patterns("__pycache__"))
    mut(root)
    r = subprocess.run([PY, str(root/"_build/build_all.py")], capture_output=True, text=True, env=ENV)
    ng = [l for l in (r.stdout+r.stderr).splitlines() if l.startswith("NG ") or "Traceback" in l or "Error" in l]
    status = "検出" if r.returncode != 0 and ng else "★見逃し"
    if status != "検出": bad_pass += 1
    print(f"[{status}] {name}: {len(ng)} 件"); [print("     ", l[:170]) for l in ng[:3]]
# 禁止語の一覧がないときは、何も作らず、説明を出して 2 で止まる（語は出さない）
if not only or "27" in only:
    root = WORK/"27"; shutil.rmtree(root, ignore_errors=True); shutil.copytree(SRC, root, ignore=shutil.ignore_patterns("__pycache__"))
    for label, env in (("環境変数なし", {k: v for k, v in os.environ.items() if k != "PUBLIC_CHECK_BANNED"}),
                       ("ファイルなし", {**os.environ, "PUBLIC_CHECK_BANNED": str(WORK/"no-such-file.txt")})):
        r = subprocess.run([PY, str(root/"_build/check_all.py")], capture_output=True, text=True, env=env)
        out = r.stdout + r.stderr
        ok = r.returncode == 2 and "PUBLIC_CHECK_BANNED" in out and not any(w in out for w in FAKE_WORDS)
        if not ok: bad_pass += 1
        print(f"[{'検出' if ok else '★見逃し'}] 27 禁止語の一覧がない（{label}）: 終了コード {r.returncode}")
shutil.rmtree(WORK, ignore_errors=True)
print("見逃し:", bad_pass)
sys.exit(1 if bad_pass else 0)
