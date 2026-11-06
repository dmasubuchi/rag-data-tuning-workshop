"""図の登録。figs_*.py の関数に @fig(ページ番号) を付けると、FIGS に入る。"""
FIGS = {}


def fig(no):
    def deco(f):
        if no in FIGS:
            raise SystemExit(f"p.{no} の図が2つある")
        FIGS[no] = f
        return f
    return deco
