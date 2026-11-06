// slide-player（MIT License, Copyright (c) 2026 dmasubuchi）の player/player.js の写し。
// このファイルは MIT License で使えます（全文はこの Repo の LICENSE）。
// このファイルのコメントにある「約束」「CONTRACT.md」は、slide-player の Repo にある約束書（CONTRACT.md）のこと。この Repo には置いていない。
// プレイヤー本体（CONTRACT.md）。1ファイル・依存なし・CSS 込み・file:// で動く。
// 動画用の描画モード（?render）のときは、下の2つの関数と body.render のほかは何もしない（約束 §3.1）。
(() => {
  'use strict';

  // ---- 動画のツールが呼ぶ2つの関数（約束 §3.1）----
  // 何よりも先に、読み込みの時点で同期に定義する（<head> で読み込まれても、ツールは読み込み直後に呼ぶ）。
  // 中身の slideDeck は、呼ばれた時点で読む（<head> で読み込まれたときは、この時点ではまだない）
  window.renderSlide = (i, st) => slideDeck.render(i, st, document.getElementById('stage'));
  window.deckInfo = () => slideDeck.info.slides.map(s => ({ id: s.id, steps: s.steps }));

  // <body> がまだないとき（<head> で読み込まれたとき）は、組み立てを DOMContentLoaded まで待つ
  const whenBodyReady = fn => {
    if (document.body) fn();
    else document.addEventListener('DOMContentLoaded', fn, { once: true });
  };

  if (new URLSearchParams(location.search).has('render')) {
    whenBodyReady(() => document.body.classList.add('render'));
    return;                                                     // 通常の表示の部品・CSS・キーは一切出さない
  }

  // ---- 決まり ----
  const STAGE_W = 1920, STAGE_H = 1080;                          // 舞台の大きさ（約束 §2.5）
  const TOAST_MS = 2500;                                         // 知らせを出しておく時間
  const TOAST_BOTTOM_PX = 72;                                    // 知らせの下端の高さ（画面の下から）。操作ボタンの帯が出ているときは、その上へ上げる
  const TOAST_GAP_PX = 12;                                       // 知らせと操作ボタンの帯のすきま
  const PAGE_NAME_FALLBACK = '別ページ';                         // ページ名を取り出せないときの呼び名（元の URL・手元のフルパスは出さない）
  const MSG_FIRST = '最初のスライドです';
  const MSG_LAST = '最後のスライドです';
  const MSG_BAD_HASH = 'URL の場所が読めないので、最初のスライドを開きました';
  const MSG_PLACE_FIRST = 'これより前の場所はありません';
  const MSG_PLACE_LAST = 'これより先の場所はありません';
  const MSG_PLACE_GONE = 'その場所のスライドが見つからないので、最初のスライドを開きました';
  const MSG_NO_FULLSCREEN = '全画面を切り替えられませんでした（このブラウザでは使えないか、許可されていません）';
  const MSG_NO_NOTES = 'ノートはありません';
  const MSG_PLACE_OTHER_PAGE = '保存領域が使えないので、別のページの場所へは移れません';
  const MSG_LINK_NONE = 'このスライドに、いま押せるリンクはありません';
  const MSG_LINK_BLOCKED = 'このリンクは開けません（許可していない種類の URL です）';
  const MSG_LINK_NO_SLIDE = id => `リンク先のスライドが見つかりません：${id}`;
  const MSG_LINK_NO_TEXT = 'このリンクには、写す文字がありません';
  const MSG_COPIED = 'コピーしました';
  const MSG_COPY_FAILED = 'コピーできませんでした';
  const MSG_COPY_BY_HAND = '手でコピーしてください';
  const MSG_CATALOG_BAD_HASH = 'URL の場所が読めないので、最初のカードを選びました';
  const MSG_CATALOG_GONE = 'その場所のカードが見つからないので、最初のカードを選びました';
  const MSG_CARD_FIRST = '最初のカードです';
  const MSG_CARD_LAST = '最後のカードです';
  const MSG_PAGE_FIRST = '最初のページです';
  const MSG_PAGE_LAST = '最後のページです';
  const MSG_CARD_BLOCKED = 'このカードは開けません（行き先がないか、許可していない種類の URL です）';
  const MSG_RENDER_FAILED = id => `このスライドは表示できません（${id}）`;
  const MSG_PRINT_TIMEOUT = '画像の読み込みが終わらないので、PDF の書き出しをやめました';
  const MSG_PRINT_FAILED = '印刷の画面を開けませんでした';
  const MSG_STAY_WRITING = '書き込みは P で PDF に残せます';
  const MSG_SIDE_NARROW = '画面が狭いので、一覧つきの画面は使えません';
  const MSG_REMOVE_ADDED = 'この追加ページを消しますか？書いたものも消えます';
  const MSG_NO_MEMO_ADDED = '追加ページにはメモを書けません';
  const MSG_OWN_OPEN = '自分用のメモを開く';
  const MSG_OWN_CLOSE = '自分用のメモを閉じる';
  const MSG_OWN_HEAD = '自分用のメモ（画面に出すと相手にも見えます）';
  const MSG_MEMO_LOW = '画面が低いのでメモを出せません';
  const MSG_MEMO_FAILED = 'メモを保存できませんでした（このページを閉じると消えます）';
  const MSG_JUMP = 'URLジャンプします';                           // ジャンプの動きの途中（前のスライドが消えている間）に、薄く出す

  // 動きの層。入場の型
  const ENTRY_STYLES = ['ppt', 'meiji'];
  // 入場：1枚の入場は ENTRY_TARGET_MS を目安に、ENTRY_MAX_MS を超えない。要素の間のずれは ENTRY_GAP_MS まで
  const ENTRY_TARGET_MS = 1500, ENTRY_MAX_MS = 2000, ENTRY_GAP_MS = 120;
  const ENTRY_MS = { fade: 400, left: 450, up: 450, blur: 500, pop: 450, wipe: 600, grow: 600, count: 800 };
  // 役目の印（data-sp-role。約束 §2.6）→ 動き。PowerPoint風（ppt）と、ぼかし・持ち上げ・弾む型（meiji）
  const ENTRY_EFFECTS = {
    ppt: { title: 'fade', sub: 'fade', item: 'left', card: 'left', bar: 'wipe', stat: 'fade', count: 'fade', node: 'left', arrow: 'fade' },
    meiji: { title: 'blur', sub: 'blur', item: 'up', card: 'up', bar: 'grow', stat: 'pop', count: 'count', node: 'pop', arrow: 'fade' },
  };
  // 動きの形。最後の形は、要素のふだんの見た目（動き終わると animation は外れる）
  const ENTRY_KEYFRAMES = {
    fade: [{ opacity: 0 }, { opacity: 1 }],
    left: [{ opacity: 0, transform: 'translateX(-48px)' }, { opacity: 1, transform: 'none' }],
    up: [{ opacity: 0, transform: 'translateY(32px)' }, { opacity: 1, transform: 'none' }],
    blur: [{ opacity: 0, filter: 'blur(12px)' }, { opacity: 1, filter: 'blur(0)' }],
    pop: [{ opacity: 0, transform: 'scale(.6)' }, { opacity: 1, transform: 'scale(1.06)', offset: 0.7 }, { opacity: 1, transform: 'none' }],
    wipe: [{ clipPath: 'inset(0 100% 0 0)' }, { clipPath: 'inset(0 0 0 0)' }],
    grow: [{ transform: 'scaleX(0)', transformOrigin: 'left center' }, { transform: 'none', transformOrigin: 'left center' }],
    count: [{ opacity: 1 }, { opacity: 1 }],                     // 数え上げは文字を変える。形は変えない（時計として使う）
  };
  const ENTRY_EASING = 'cubic-bezier(.2, .8, .2, 1)';
  // 指す層。光の半径は舞台の px（画面では舞台の縮小に合わせる）。光を使っている間、マウスの移動で帯を出すのは画面の下の端から CONTROLS_EDGE_PX まで
  const LIGHT_RADIUS = 210;
  const CONTROLS_EDGE_PX = 120;
  // 書き込み：色（9色）・太さ・大きさ（舞台の px）・描き味・蛍光ペン・種類ごとの最初の値
  const WRITE_COLORS = ['#d62828', '#f77f00', '#e0a800', '#2a9d3f', '#1b9bd1', '#1f5fbf', '#7b3fbf', '#222222', '#ffffff'];
  const WRITE_WIDTHS = [['細', 6], ['太', 12]];
  const WRITE_SIZES = [['小', 28], ['中', 32], ['大', 40]];
  const WRITE_FEELS = [['そのまま', 0], ['弱', 2], ['中', 4], ['強', 7]];
  const WRITE_KINDS = ['rect', 'ellipse', 'line', 'arrow', 'text', 'free'];
  const WRITE_DEFAULTS = {
    rect: { c: '#1f5fbf', w: 6 }, ellipse: { c: '#d62828', w: 6 }, line: { c: '#222222', w: 6 }, arrow: { c: '#d62828', w: 6 },
    text: { c: '#222222', w: 32 }, free: { c: '#222222', w: 6, r: 2 },
  };
  const WRITE_HL = { color: '#ffd60a', width: 28, alpha: 0.4 };
  const WRITE_STEP = 5;                                          // 点を取り直す間隔（舞台の px）
  const WRITE_CLICK = 12;                                        // これより短い線はクリックとして何も描かない（舞台の px）
  const WRITE_HANDLE = 22;                                       // つまみに当たる範囲（舞台の px）
  const WRITE_LINE_H = 1.4;                                      // 文字の行の高さ
  const LINK_WIGGLE = [{ transform: 'rotate(0)' }, { transform: 'rotate(-8deg) scale(1.1)', offset: 0.25 }, { transform: 'rotate(8deg) scale(1.1)', offset: 0.75 }, { transform: 'rotate(0)' }];

  // 目次（約束 §4）：1ページのカードの数を決める幅（px）。この幅以上で3枚、こちら以上で2枚、それより狭いと1枚
  const CATALOG_WIDE_PX = 1200, CATALOG_MID_PX = 760;
  const CATALOG_KEYS_HINT = '↑↓ 選ぶ　Shift＋↑↓ 前後のページ　Enter 開く　1〜9 N番目を開く　← → 直近の場所　? 操作の一覧';
  const CATALOG_HELP_KEYS = [                                    // 目次の操作の一覧（?）に出すキー
    [['↑', '↓'], 'カードを順に選ぶ'],
    [['Shift＋↑', 'Shift＋↓'], '前後のページへ（そのページの最初のカードを選ぶ）'],
    [['Enter'], '選んでいるカードを開く'],
    [['1〜9'], '一覧の最初から数えて1〜9番目のカードを開く'],
    [['←', '→'], '直近の場所を戻る・進む（先の場所がないときの → は ↓ と同じ）'],
    [['指で左へ払う', '右へ払う'], '→・← と同じ（iPhone・iPad）'],
    [['指で上へ払う', '下へ払う'], '↓・↑ と同じ'],
    [['?'], 'この一覧を開く・閉じる'],
    [['Esc'], '開いているものを閉じる'],
  ];

  // 指で払う操作（iPhone・iPad）
  const SWIPE_KEYS = { left: 'ArrowRight', right: 'ArrowLeft', up: 'ArrowDown', down: 'ArrowUp' };   // 払った向き → 同じ動きのキー（指を左へ払う＝→。ページをめくる・スクロールする向き）
  const SWIPE_MIN_RATIO = 0.06;                                  // 払いの距離の下限：払った向きの画面の幅（縦なら高さ）の割合
  const SWIPE_MIN_PX = 30;                                       // 同じく px の下限（大きい画面でも、小さい画面でも、触れただけを払いと見なさない）
  const SWIPE_DIRECTION_RATIO = 1.5;                             // 向きがはっきりしている：大きい方の距離が、小さい方のこの倍以上
  const SWIPE_MAX_MS = 700;                                      // 触れてから離すまでの時間の上限（ゆっくり動かしたものは払いではない）
  const SWIPE_EDGE_PX = 20;                                      // 画面の端からこれ以内で始めた払いは扱わない（iPhone・iPad のシステムの払いと重なる）
  const SWIPE_ZOOM_SCALE = 1.01;                                 // 2本指で拡大している間（visualViewport.scale がこれを超える）は扱わない
  const SWIPE_UI = '.sp-controls, .sp-notes, .sp-side, .sp-memo, .sp-toast, .sp-pager';   // 払いの扱わない部品（プレイヤー自身の画面の部品）

  // メモ。localStorage に、欄1つを1つのキーで保存する：「sp-memo-v1 <ページの URL> <スライドの id> <shared|own>」
  const MEMO_KEY_PREFIX = 'sp-memo-v1';
  const MEMO_MAX_CHARS = 4000;                                   // 1つの欄の上限。これより長い値・文字列でない値は、そのキーだけ捨てる
  const MEMO_SAVE_MS = 500;                                      // 書いてから保存までの待ち
  const MEMO_BAND_MIN_PX = 96, MEMO_BAND_MAX_PX = 200, MEMO_BAND_VH = 20;   // メモの帯の高さ：画面の高さの 20%、最小 96px、最大 200px
  const MEMO_BAND_H = `clamp(${MEMO_BAND_MIN_PX}px, ${MEMO_BAND_VH}vh, ${MEMO_BAND_MAX_PX}px)`;   // 同じ高さ（CSS）
  const MEMO_MIN_CENTER_PX = 240;                                // 帯を出すのに、中央の領域に残る高さの下限

  // リンク（約束 §2.4、§3.3）
  const LINK_ID_RE = /^([A-Za-z][A-Za-z0-9_-]*)(?:\.(\d+))?$/;       // 同じデッキの中の行き先：「ID」「ID.段階」
  const LINK_PAGE_SCHEMES = ['file:', 'http:', 'https:'];        // 別のページへ移ってよい URL の種類（リンク・目次のカード・H の目次・保存した場所のページが、すべてこの1か所を使う）
  const LINK_EXTERNAL_SCHEMES = ['http:', 'https:'];             // 新しいタブで開いてよい URL の種類
  const LINK_MARKS = { jump: '→', external: '↗', more: '＋', copy: '⧉', broken: '⚠' };   // 印の文字（舞台の外の層 .sp-linkmarks に重ねる）

  // 設定（約束 §3.2）。localStorage に {controls, notes, side, memo} を1つ保存する
  const SETTINGS_KEY = 'sp-settings-v1';
  const CONTROLS_MODES = ['auto', 'always', 'never'];            // 操作ボタンの出し方：自動で消す・いつも出す・出さない
  const CONTROLS_LABELS = { auto: '自動で消す', always: 'いつも出す', never: '出さない' };
  const CONTROLS_HIDE_MS = 3000;                                 // 自動で消すまでの時間（動きがなかったとき）
  const NOTES_W = 'min(520px, max(320px, 28vw))';                // ノートの幅（CSS）
  const PRINT_WAIT_MS = 5000;                                    // PDF の書き出し（P）が、字体と画像の読み込みを待つ上限
  const THUMB_W = 256, THUMB_H = 144;                            // 縮小一覧のサムネイルの枠（舞台と同じ縦横比）
  const SIDE_MIN_PX = 180, SIDE_MAX_PX = 300, SIDE_VW = 18;      // 一覧つきの画面（T）の左の列の幅：画面の幅の 18%、最小 180px、最大 300px
  const SIDE_W = `clamp(${SIDE_MIN_PX}px, ${SIDE_VW}vw, ${SIDE_MAX_PX}px)`;   // 同じ幅（CSS）
  const SIDE_MIN_CENTER_PX = 400;                                // 列を出すのに、中央の領域（列とノートを除いた所）に残る幅の下限

  // 切り替えの動き（ブラウザの View Transitions）
  const MOTION_SLIDE_MS = 300;                                   // 隣のスライドへ：左右に流れる時間
  const MOTION_SLIDE_EASE = 'cubic-bezier(0.65, 0, 0.35, 1)';    // だんだん速くなり、だんだんゆっくり止まる
  const MOTION_JUMP_MS = 500;                                    // ジャンプ：全体の時間（前半で今のスライドが消え、後半で次のスライドが現れる）
  const MOTION_JUMP_HALF_MS = MOTION_JUMP_MS / 2;
  const MOTION_JUMP_MSG_ALPHA = 0.5;                             // 「URLジャンプします」の濃さ（薄い文字）
  const MOTION_ARRIVE_MS = 250;                                  // 別のページへ移ったとき、着いた側のフェードインの時間
  const ARRIVE_KEY = 'sp-arrive-v1';                             // sessionStorage：移る直前の時刻（プレイヤー自身が移したことを、着いた側へ伝える）
  const ARRIVE_WINDOW_MS = 10000;                                // 着いた側が使える時間（書いてから）
  const UI_FONT = 'system-ui, "Hiragino Sans", "Meiryo", sans-serif';   // 縮小一覧の、プレイヤー自身の文字の字体

  // 直近の場所（約束 §3.4）。sessionStorage に {v: 1, items: [{vid, page, kind, ref, step}], pos, restore: {vid, t} | null}
  const PLACES_KEY = 'sp-places-v1';
  const PLACES_MAX = 10;                                         // 覚える場所の数
  const PLACE_STEP_MAX = 10000;                                  // 保存した段階の上限（これを超えるものは壊れたデータとして捨てる）
  const RESTORE_MS = 10000;                                      // 復元先を使える時間（保存してから）
  const ADD_RE = /^x[0-9]{1,6}$/;                                // 追加ページの識別子（このページを開いている間だけ）
  const VID_RE = /^[a-z0-9]{8,16}$/;                             // 訪問の識別子
  const REF_RE = /^[A-Za-z][A-Za-z0-9_-]*$/;                     // スライドとデッキの ID の形（約束 §2.3）

  // プレイヤーのクラス名はすべて sp- で始める。header・main・footer の要素は使わない（約束 §2.5）
  const CSS = `
html, body { margin: 0 !important; padding: 0 !important; overflow: hidden !important; background: #14181d !important; }
/* 1本指のスクロールをブラウザに取られないよう止める（指で払う操作を自分で見分けるため）。2本指の拡大は残す。
   中身の中のスクロールできる要素・ノート・縮小一覧は、それぞれがスクロールする要素なので、ブラウザの決まりで指でスクロールできるまま。
   拡大している間（createSwipe が html に sp-zoomed を付ける）は、拡大した画面を指で動かせるよう、外す */
html, body { touch-action: pinch-zoom; overscroll-behavior: none; }
html.sp-zoomed, html.sp-zoomed body { touch-action: auto; }
.sp-toast { position: fixed; left: 50%; bottom: ${TOAST_BOTTOM_PX}px; transform: translateX(-50%); z-index: 1000; max-width: min(80vw, 640px);
  box-sizing: border-box; padding: 10px 18px; border-radius: 8px; background: rgba(20, 24, 29, .92); color: #fff; font: 15px/1.5 system-ui, "Hiragino Sans", "Meiryo", sans-serif;
  text-align: center; pointer-events: none; box-shadow: 0 4px 16px rgba(0, 0, 0, .35); }

/* 描けなかったスライドの代わりの表示：舞台（#stage）の中いっぱい。中身の CSS に左右されないよう、使う指定は自分で全部決める */
.sp-render-error { position: absolute; left: 0; top: 0; right: 0; bottom: 0; box-sizing: border-box; display: flex; align-items: center; justify-content: center;
  margin: 0; padding: 0 120px; background: #2b3038; color: #f2f5f8; text-align: center; font: 700 64px/1.5 ${UI_FONT}; overflow-wrap: anywhere; }

/* 操作ボタンの帯：画面の下に重ねる（舞台の大きさは変えない）。出ていないときは visibility で外し、Tab も届かない */
.sp-controls { position: fixed; left: 0; right: 0; bottom: 0; z-index: 900; box-sizing: border-box; display: flex; flex-wrap: wrap;
  align-items: center; justify-content: center; gap: 6px 8px; padding: 8px 12px; background: rgba(20, 24, 29, .9);
  border-top: 1px solid rgba(255, 255, 255, .14); color: #e8edf2; font: 14px/1.4 system-ui, "Hiragino Sans", "Meiryo", sans-serif;
  opacity: 0; visibility: hidden; transition: opacity .2s, visibility 0s linear .2s; }
.sp-controls.sp-on { opacity: 1; visibility: visible; transition: opacity .2s; }
.sp-controls.sp-beside-notes { right: ${NOTES_W}; }
.sp-controls.sp-beside-side { left: ${SIDE_W}; }
.sp-pos { padding: 0 8px; white-space: nowrap; font-variant-numeric: tabular-nums; }
.sp-btn { box-sizing: border-box; min-height: 34px; padding: 5px 10px; border: 1px solid rgba(255, 255, 255, .3); border-radius: 6px;
  background: rgba(255, 255, 255, .08); color: inherit; font: inherit; white-space: nowrap; cursor: pointer; }
.sp-btn:hover { background: rgba(255, 255, 255, .2); }
.sp-btn:focus-visible { outline: 2px solid #7fb6ff; outline-offset: 2px; }
.sp-btn[aria-pressed="true"], .sp-btn[aria-checked="true"] { background: #2f6fb5; border-color: #8fc0ff; }
@media (prefers-reduced-motion: reduce) { .sp-controls, .sp-controls.sp-on { transition: none; } }

/* ノート：右に出す。舞台はこの幅を除いた残りに置く（fitStage） */
.sp-notes { position: fixed; top: 0; right: 0; bottom: 0; z-index: 800; box-sizing: border-box; width: ${NOTES_W}; display: flex; flex-direction: column;
  background: #1d232b; color: #e8edf2; border-left: 1px solid rgba(255, 255, 255, .14); font: 17px/1.7 system-ui, "Hiragino Sans", "Meiryo", sans-serif; }
.sp-notes-head { flex: none; padding: 16px 20px 12px; border-bottom: 1px solid rgba(255, 255, 255, .14); }
.sp-notes-title { font-size: 18px; font-weight: 700; line-height: 1.5; overflow-wrap: anywhere; }
.sp-notes-time { margin-top: 2px; font-size: 14px; color: #aab4bf; }
.sp-notes-body { flex: 1; min-height: 0; overflow: auto; padding: 16px 20px; white-space: pre-wrap; overflow-wrap: anywhere; }
.sp-notes-body.sp-notes-empty { color: #8b96a3; }
.sp-notes-own { flex: none; padding: 10px 20px 14px; border-top: 1px solid rgba(255, 255, 255, .14); }
.sp-notes-own-toggle { padding: 2px 12px; font-size: 14px; }
.sp-notes-own-head { margin-top: 10px; color: #9fb3c8; font: 700 13px/1.5 system-ui, "Hiragino Sans", "Meiryo", sans-serif; }
.sp-notes-memo { display: block; box-sizing: border-box; width: 100%; height: 120px; margin: 4px 0 0; padding: 4px 8px; resize: none; border: 1px solid rgba(255, 255, 255, .25); border-radius: 6px;
  background: #11161c; color: #f2f5f8; font: 17px/1.5 system-ui, "Hiragino Sans", "Meiryo", sans-serif; }
.sp-notes-memo:focus-visible { outline: 2px solid #7fb6ff; outline-offset: 1px; }

/* メモの帯：画面の下、左の列とノートの間の幅いっぱい。舞台は帯の上の領域に収める（centerArea・fitStage）。操作ボタンの帯と知らせは帯の上に置く */
.sp-memo { position: fixed; left: 0; right: 0; bottom: 0; z-index: 800; box-sizing: border-box; height: ${MEMO_BAND_H}; display: flex; flex-direction: column;
  padding: 6px 12px 8px; background: #1d232b; border-top: 1px solid rgba(255, 255, 255, .14); }
.sp-memo.sp-beside-notes { right: ${NOTES_W}; }
.sp-memo.sp-beside-side { left: ${SIDE_W}; }
.sp-memo-head { flex: none; display: flex; align-items: center; justify-content: space-between; color: #9fb3c8; font: 700 12px/1.5 ${UI_FONT}; }
.sp-memo-export { flex: none; padding: 1px 10px; font-size: 12px; }
.sp-memo-export:disabled { opacity: .4; cursor: default; }
.sp-memo-text { flex: 1; min-height: 0; box-sizing: border-box; width: 100%; margin: 0; padding: 4px 8px; resize: none; border: 1px solid rgba(255, 255, 255, .25); border-radius: 6px;
  background: #11161c; color: #f2f5f8; font: 20px/1.4 ${UI_FONT}; }
.sp-memo-text:focus-visible { outline: 2px solid #7fb6ff; outline-offset: 1px; }

/* 一覧つきの画面（T）の左の列：全スライドの縮小を縦に並べる。舞台は列とノートを除いた中央の領域に置く（centerArea・fitStage）。
   縦にスクロールするのはこの列だけ。縮小一覧と同じく、継がれる文字の指定は、プレイヤー自身の文字の要素（節の題・キャプション）だけに付ける。
   .sp-side・.sp-side-item・.sp-side-frame には付けない（中身の描画先へ継がれて、メインの舞台と見た目が変わるため。約束 §2.5） */
.sp-side { position: fixed; top: 0; left: 0; bottom: 0; z-index: 800; box-sizing: border-box; width: ${SIDE_W}; overflow-x: hidden; overflow-y: auto;
  padding: 12px; background: #1d232b; border-right: 1px solid rgba(255, 255, 255, .14); overscroll-behavior: contain; }
.sp-side-section { margin: 14px 0 8px; color: #9fb3c8; font: 700 12px/1.5 ${UI_FONT}; overflow-wrap: anywhere; }
.sp-side-item { position: relative; box-sizing: border-box; margin: 0 0 12px; scroll-margin: 8px 0; cursor: pointer; outline: none; -webkit-tap-highlight-color: transparent; }
.sp-side-frame { position: relative; box-sizing: border-box; width: 100%; aspect-ratio: 16 / 9; overflow: hidden; border-radius: 4px; background: #fff; }
.sp-side-frame > .sp-target { pointer-events: none; user-select: none; -webkit-user-select: none; }
.sp-side-item.sp-thumb-broken .sp-side-frame { background: #4a3030; }
.sp-side-caption { margin-top: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #c5cfda; font: 12px/1.4 ${UI_FONT}; }
.sp-side-item.sp-has-memo .sp-side-caption { padding-right: 1.8em; }
.sp-side-memo { position: absolute; right: 0; bottom: 0; color: #f0b429; font: 12px/1.4 ${UI_FONT}; }
.sp-side-item:hover .sp-side-frame { box-shadow: 0 0 0 2px rgba(255, 255, 255, .5); }
.sp-side-item.sp-current .sp-side-frame { outline: 3px solid #f0b429; outline-offset: 2px; }
.sp-side-item.sp-current .sp-side-caption { color: #f0b429; font-weight: 700; }

/* 操作の一覧：画面全体を覆う（背景を押すと閉じる） */
.sp-help { position: fixed; left: 0; top: 0; right: 0; bottom: 0; z-index: 950; display: flex; align-items: center; justify-content: center;
  background: rgba(8, 10, 13, .72); }
.sp-help-panel { box-sizing: border-box; width: min(760px, calc(100vw - 32px)); max-height: calc(100vh - 32px); overflow: auto; padding: 22px 26px;
  border-radius: 12px; background: #1d232b; color: #e8edf2; box-shadow: 0 12px 40px rgba(0, 0, 0, .5); outline: none;
  font: 15px/1.6 system-ui, "Hiragino Sans", "Meiryo", sans-serif; }
.sp-help-title { margin: 0 0 12px; font-size: 20px; font-weight: 700; }
.sp-help-section { margin: 18px 0 8px; font-size: 14px; font-weight: 700; color: #9fb3c8; }
.sp-help-row { display: grid; grid-template-columns: minmax(150px, 38%) 1fr; gap: 4px 14px; padding: 4px 0; border-bottom: 1px solid rgba(255, 255, 255, .08); }
.sp-key { display: inline-block; min-width: 1.6em; margin: 0 4px 2px 0; padding: 1px 7px; border: 1px solid rgba(255, 255, 255, .35); border-radius: 5px;
  background: rgba(255, 255, 255, .08); font: 600 13px/1.5 ui-monospace, Menlo, monospace; text-align: center; }
.sp-help-choices { display: flex; flex-wrap: wrap; gap: 8px; }
.sp-help-close { margin-top: 18px; text-align: right; }

/* 縮小一覧：画面全体を覆う（背景を押すと閉じる）。サムネイルは 1920×1080 の描画先を transform で縮め、決まった大きさの枠に置く。
   一覧の中（.sp-overview-panel）だけがスクロールする。操作の一覧（950）はこの上に重なる。
   文字の色・字体・行の高さなど、継がれる文字の指定は、プレイヤー自身の文字の要素（見出し・ラベル・キャプション・ボタン）だけに付ける。
   .sp-overview・.sp-overview-panel・.sp-thumb・.sp-thumb-frame には付けない（中身の描画先へ継がれて、メインの舞台と見た目が変わるため。約束 §2.5） */
.sp-overview { position: fixed; left: 0; top: 0; right: 0; bottom: 0; z-index: 940; display: flex; align-items: center; justify-content: center;
  background: rgba(8, 10, 13, .82); }
.sp-overview-panel { box-sizing: border-box; width: min(1500px, calc(100vw - 32px)); max-height: calc(100vh - 32px); overflow: auto; padding: 16px 22px 24px;
  border-radius: 12px; background: #1d232b; box-shadow: 0 12px 40px rgba(0, 0, 0, .5); outline: none; }
.sp-overview-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.sp-overview-title { color: #e8edf2; font: 700 20px/1.5 ${UI_FONT}; }
.sp-overview-head .sp-btn, .sp-recent-item { color: #e8edf2; font: 15px/1.6 ${UI_FONT}; }
.sp-overview-label, .sp-section-title { margin: 16px 0 8px; color: #9fb3c8; font: 700 14px/1.6 ${UI_FONT}; }
.sp-recent { display: flex; flex-wrap: wrap; gap: 8px; }
.sp-recent-item { max-width: 100%; white-space: normal; text-align: left; overflow-wrap: anywhere; }
.sp-recent-item.sp-recent-now { background: #2f6fb5; border-color: #8fc0ff; font-weight: 700; }
.sp-recent-item.sp-recent-now::before { content: "● "; }
.sp-sections { padding-top: 8px; }
.sp-grid { display: flex; flex-wrap: wrap; gap: 20px 14px; }
.sp-thumb { box-sizing: border-box; width: ${THUMB_W}px; cursor: pointer; outline: none; -webkit-tap-highlight-color: transparent; }
.sp-thumb-frame { position: relative; width: ${THUMB_W}px; height: ${THUMB_H}px; overflow: hidden; border-radius: 4px; background: #fff; }
.sp-thumb-frame > .sp-target { pointer-events: none; user-select: none; -webkit-user-select: none; }
.sp-thumb-broken .sp-thumb-frame { background: #4a3030; }
.sp-thumb-caption { margin-top: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #c5cfda; font: 13px/1.4 ${UI_FONT}; }
.sp-thumb:hover .sp-thumb-frame { box-shadow: 0 0 0 2px rgba(255, 255, 255, .5); }
.sp-thumb.sp-selected .sp-thumb-frame { box-shadow: 0 0 0 3px #7fb6ff; }
.sp-thumb.sp-current .sp-thumb-frame { outline: 3px solid #f0b429; outline-offset: 5px; }
.sp-thumb.sp-current .sp-thumb-caption { color: #f0b429; font-weight: 700; }

/* リンクの印：舞台（#stage）の中の data-link の要素に、カーソルと枠を付ける。通常の表示のときだけ。
   中身の配置（幅・行の高さ・折り返し・まわりの位置）は変えない：枠は outline（配置に影響しない）、種類ごとの印の文字（→ ↗ ＋ ⧉ ⚠）は、
   舞台の中に足さず、舞台の外の層 .sp-linkmarks に、要素の位置に合わせて重ねる（layoutLinkMarks）。
   縮小一覧のサムネイルには data-sp-kind が付かないので、印も出ない */
body:not(.render) #stage [data-sp-kind] { cursor: pointer; }
body:not(.render) #stage [data-sp-kind="broken"] { outline: 3px dashed #d9534f; outline-offset: 4px; }
body:not(.render) #stage [data-sp-kind]:focus-visible { outline: 4px solid #2f6fb5; outline-offset: 4px; }
.sp-linkmarks { position: fixed; left: 0; top: 0; width: 0; height: 0; z-index: 10; pointer-events: none; }
.sp-linkmark { position: absolute; margin: 0; padding: 0; font-family: ${UI_FONT}; font-weight: 700; line-height: 1; white-space: nowrap; opacity: .85;
  pointer-events: none; user-select: none; -webkit-user-select: none; }
.sp-linkmark[data-kind="broken"] { color: #d9534f; opacity: 1; }

/* リンクを表示（L）：画面全体を少し暗くし、各リンクの要素を枠で囲んで、移動先を札で示す。場所のないリンクは隅の一覧。
   枠はプレイヤーのボタン（.sp-btn）で、押すとそのリンクを開く。位置は layoutLinkView が要素の位置に合わせて置く */
.sp-linkview { position: fixed; left: 0; top: 0; right: 0; bottom: 0; z-index: 930; background: rgba(8, 10, 13, .45); outline: none; }
.sp-linkpanel { position: absolute; right: 16px; top: 16px; box-sizing: border-box; width: max-content; max-width: min(420px, calc(100vw - 32px));
  max-height: calc(100vh - 32px); overflow: auto; padding: 10px 12px; border-radius: 10px; background: #1d232b; box-shadow: 0 8px 28px rgba(0, 0, 0, .45); }
.sp-linkpanel-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; color: #e8edf2; font: 700 15px/1.5 ${UI_FONT}; }
.sp-linklist { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.sp-linklist-title { color: #9fb3c8; font: 700 13px/1.5 ${UI_FONT}; }
.sp-linklist-item { display: flex; flex-direction: column; align-items: flex-start; gap: 1px; width: 100%; padding: 6px 10px; text-align: left; white-space: normal;
  overflow-wrap: anywhere; font: 14px/1.5 ${UI_FONT}; color: #e8edf2; }
.sp-linklist-label { font-weight: 700; }
.sp-linklist-dest { color: #ffd54a; font-size: 13px; }
.sp-linklist-item[data-kind="broken"] .sp-linklist-dest { color: #ff9b9b; }
.sp-linkframe { position: absolute; box-sizing: border-box; min-height: 0; margin: 0; padding: 0; border: 3px solid #ffd54a; border-radius: 8px;
  background: rgba(255, 213, 74, .12); }
.sp-linkframe:hover { background: rgba(255, 213, 74, .3); }
.sp-linkframe[data-kind="broken"] { border-color: #ff6b6b; border-style: dashed; background: rgba(255, 107, 107, .14); }
.sp-linkframe[data-kind="broken"]:hover { background: rgba(255, 107, 107, .3); }
.sp-linkframe:focus-visible { outline: 3px solid #7fb6ff; outline-offset: 3px; }
.sp-linktag { position: absolute; left: -3px; top: calc(100% + 6px); box-sizing: border-box; width: max-content; max-width: min(420px, 70vw); padding: 3px 10px;
  border-radius: 6px; background: #ffd54a; color: #14181d; font: 700 14px/1.5 ${UI_FONT}; text-align: left; white-space: normal; overflow-wrap: anywhere; pointer-events: none; }
.sp-linkframe.sp-above .sp-linktag { top: auto; bottom: calc(100% + 6px); }
.sp-linkframe.sp-right .sp-linktag { left: auto; right: -3px; }
.sp-linkframe[data-kind="broken"] .sp-linktag { background: #ff6b6b; color: #2a0b0b; }

/* 目次：画面いっぱいに固定で出す。ページ自身の CSS（body の余白・flex・要素名での指定）に左右されないよう、
   自分の入れ物と sp- のクラスで、使う指定を（文字の大きさ・余白・色まで）すべて自分で決める。h1・nav・kbd などの要素は使わない。
   項目の一覧だけは意味のある ul・li を使うが、all: unset で要素名のページの指定（display・float・position・border・list-style など）を
   すべて外してから、display などを自分で決める */
.sp-catalog { position: fixed; left: 0; top: 0; right: 0; bottom: 0; z-index: 1; box-sizing: border-box; display: flex; flex-direction: column; overflow: hidden;
  padding: clamp(14px, 3.4vh, 38px) clamp(16px, 4vw, 64px) clamp(10px, 2vh, 22px); background: #14181d; color: #e8edf2; text-align: left; font: 16px/1.5 ${UI_FONT}; }
.sp-catalog [hidden] { display: none !important; }
.sp-catalog-head { flex: none; margin: 0 0 clamp(10px, 2.2vh, 26px); padding: 0; }
.sp-catalog-title { margin: 0; padding: 0; color: #f2f5f8; font: 800 clamp(20px, 2.5vw, 36px)/1.3 ${UI_FONT}; overflow-wrap: anywhere; }
.sp-catalog-lead { margin: 4px 0 0; padding: 0; color: #aab4bf; font: 400 clamp(13px, 1.15vw, 17px)/1.6 ${UI_FONT}; overflow-wrap: anywhere; }
.sp-cards { flex: 1 1 0; min-height: 0; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(var(--n, 3), minmax(0, 1fr));
  grid-template-rows: minmax(0, 1fr); gap: clamp(10px, 2vw, 28px); }
.sp-card { position: relative; box-sizing: border-box; display: flex; flex-direction: column; min-width: 0; min-height: 0; margin: 0; overflow: hidden; cursor: pointer;
  padding: clamp(12px, 2.4vh, 28px) clamp(14px, 1.6vw, 26px); border: 0; border-top: 10px solid var(--c, #868e96); border-radius: 14px;
  background: #e6ebf1; color: #1d2733; outline: none; user-select: none; -webkit-user-select: none; -webkit-tap-highlight-color: transparent; }
.sp-card.sp-selected { background: #fff; outline: 4px solid #7fb6ff; outline-offset: 4px; }
.sp-card-label { flex: none; margin: 0; padding: 0; color: var(--c, #5b6675); font: 800 clamp(14px, 1.3vw, 20px)/1.4 ${UI_FONT}; }
.sp-card-title { flex: none; margin: .2em 0 .6em; padding: 0; color: #1d2733; font: 800 clamp(19px, 2.1vw, 32px)/1.3 ${UI_FONT}; overflow-wrap: anywhere; }
.sp-card-items { all: unset; box-sizing: border-box; display: block; flex: 1 1 auto; min-height: 0; overflow: hidden; margin: 0; padding: 0 0 0 1.2em;
  list-style: disc outside; color: #46515e; font: 400 clamp(14px, 1.2vw, 19px)/1.7 ${UI_FONT}; }
.sp-card-item { all: unset; display: list-item; overflow-wrap: anywhere; }
.sp-card-meta { flex: none; margin: auto 0 0; padding: .8em 0 0; color: #5b6675; font: 400 clamp(12px, 1vw, 16px)/1.5 ${UI_FONT}; overflow-wrap: anywhere; }
.sp-card.sp-card-bare { justify-content: center; }
.sp-card.sp-card-bare .sp-card-title { margin: 0; }
.sp-pager { flex: none; display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 8px; margin: clamp(12px, 2.2vh, 22px) 0 0; padding: 0; }
.sp-pager-btn[aria-current="page"] { background: #2f6fb5; border-color: #8fc0ff; }
.sp-catalog-hint { flex: none; margin: clamp(10px, 1.6vh, 16px) 0 0; padding: 0; color: #8b96a3; text-align: center; font: 400 12px/1.5 ${UI_FONT}; }

/* 補足（more）と、写せなかったコピーの文字：画面全体を覆う（背景を押すと閉じる） */
.sp-more { position: fixed; left: 0; top: 0; right: 0; bottom: 0; z-index: 935; display: flex; align-items: center; justify-content: center; background: rgba(8, 10, 13, .72); }
.sp-more-panel { box-sizing: border-box; width: min(640px, calc(100vw - 32px)); max-height: calc(100vh - 32px); overflow: auto; padding: 20px 24px; border-radius: 12px;
  background: #1d232b; color: #e8edf2; box-shadow: 0 12px 40px rgba(0, 0, 0, .5); outline: none; font: 16px/1.7 ${UI_FONT}; }
.sp-more-title { margin: 0 0 8px; font-size: 19px; font-weight: 700; line-height: 1.5; overflow-wrap: anywhere; }
.sp-more-text { white-space: pre-wrap; overflow-wrap: anywhere; user-select: text; -webkit-user-select: text; }
.sp-more-text.sp-more-copy { padding: 10px 14px; border-radius: 8px; background: #0b1118; font: 16px/1.6 ui-monospace, Menlo, monospace; }
.sp-more-hint { margin-top: 12px; color: #f0b429; font-size: 14px; line-height: 1.6; }
.sp-more-close { margin-top: 16px; text-align: right; }

/* 切り替えの動き（ブラウザの View Transitions）。名前と動きは、動いている間だけ html に付く sp-vt-*（何を動かすか）と sp-mv-*（動きの種類）で有効になる
   （ふだんは舞台に名前を付けない。?render はこの CSS を読み込まない）。
   stage：舞台（#stage）だけを動かし、その group を overflow: clip で舞台の枠の中に収める。ページ全体（root）は動かさない（操作ボタン・ノートも動かさない）。
   root：ページ全体を動かす（WebKit。舞台だけに名前を付けると、入ってくる側が写らなかった） */
html.sp-vt-stage #stage { view-transition-name: sp-stage; }
html.sp-vt-stage .sp-controls { view-transition-name: sp-controls; }
html.sp-vt-stage .sp-linkmarks { visibility: hidden; }   /* 印の層は舞台の外で動かない。舞台だけを動かす間は、移動先の印だけが見えないよう隠す（終わると最新の位置で戻る）。root は印も一緒に写って流れる */
html.sp-vt-stage::view-transition-group(sp-stage) { overflow: clip; }
html.sp-vt-stage::view-transition-group(root) { animation: none; }
html.sp-vt-stage::view-transition-old(root) { display: none; }
html.sp-vt-stage::view-transition-new(root) { animation: none; mix-blend-mode: normal; }
html.sp-vt-stage::view-transition-old(sp-controls) { display: none; }
html.sp-vt-stage::view-transition-new(sp-controls) { animation: none; mix-blend-mode: normal; }
/* 一覧つきの画面の左の列は動かさない：別の名前を付けて root から分け、古い写しは出さず、新しい写しは位置も透明度も動かさない。
   root（WebKit）は、列を出している間は動かさない（motionKind）ので、ここには書かない：本物の WebKit は、名前を付けた列の新しい写しを描かない */
html.sp-vt-stage .sp-side { view-transition-name: sp-side; }
html.sp-vt-stage::view-transition-group(sp-side) { animation: none; }
html.sp-vt-stage::view-transition-old(sp-side) { display: none; }
html.sp-vt-stage::view-transition-new(sp-side) { animation: none; mix-blend-mode: normal; }
html.sp-vt-root::view-transition { background: #14181d; }
@keyframes sp-out-left { from { transform: translateX(0); } to { transform: translateX(-100%); } }
@keyframes sp-out-right { from { transform: translateX(0); } to { transform: translateX(100%); } }
@keyframes sp-in-right { from { transform: translateX(100%); } to { transform: translateX(0); } }
@keyframes sp-in-left { from { transform: translateX(-100%); } to { transform: translateX(0); } }
@keyframes sp-fade-out { from { opacity: 1; } to { opacity: 0; } }
@keyframes sp-fade-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes sp-jump-msg { 0% { opacity: 0; } 40%, 60% { opacity: ${MOTION_JUMP_MSG_ALPHA}; } 100% { opacity: 0; } }
/* 隣のスライドへ：次へは左へ流れる（今のスライドが左へ出て、次が右から入る）。前へは逆 */
html.sp-vt-stage.sp-mv-next::view-transition-old(sp-stage), html.sp-vt-root.sp-mv-next::view-transition-old(root) {
  animation: sp-out-left ${MOTION_SLIDE_MS}ms ${MOTION_SLIDE_EASE} both; mix-blend-mode: normal; }
html.sp-vt-stage.sp-mv-next::view-transition-new(sp-stage), html.sp-vt-root.sp-mv-next::view-transition-new(root) {
  animation: sp-in-right ${MOTION_SLIDE_MS}ms ${MOTION_SLIDE_EASE} both; mix-blend-mode: normal; }
html.sp-vt-stage.sp-mv-prev::view-transition-old(sp-stage), html.sp-vt-root.sp-mv-prev::view-transition-old(root) {
  animation: sp-out-right ${MOTION_SLIDE_MS}ms ${MOTION_SLIDE_EASE} both; mix-blend-mode: normal; }
html.sp-vt-stage.sp-mv-prev::view-transition-new(sp-stage), html.sp-vt-root.sp-mv-prev::view-transition-new(root) {
  animation: sp-in-left ${MOTION_SLIDE_MS}ms ${MOTION_SLIDE_EASE} both; mix-blend-mode: normal; }
/* ジャンプ：前半で今のスライドが消え、後半で次のスライドが現れる。消えている間の真ん中に、薄い文字を出す（.sp-jumpmsg：舞台の枠の中央に重ねる） */
html.sp-vt-stage.sp-mv-jump::view-transition-old(sp-stage), html.sp-vt-root.sp-mv-jump::view-transition-old(root) {
  animation: sp-fade-out ${MOTION_JUMP_HALF_MS}ms ease both; mix-blend-mode: normal; }
html.sp-vt-stage.sp-mv-jump::view-transition-new(sp-stage), html.sp-vt-root.sp-mv-jump::view-transition-new(root) {
  animation: sp-fade-in ${MOTION_JUMP_HALF_MS}ms ease ${MOTION_JUMP_HALF_MS}ms both; mix-blend-mode: normal; }
.sp-jumpmsg { position: fixed; z-index: 1000; box-sizing: border-box; display: flex; align-items: center; justify-content: center; padding: 0 16px;
  color: #e8edf2; font: 20px/1.5 ${UI_FONT}; text-align: center; pointer-events: none; view-transition-name: sp-jump; }
html.sp-mv-jump::view-transition-group(sp-jump) { animation: none; }
html.sp-mv-jump::view-transition-new(sp-jump) { animation: sp-jump-msg ${MOTION_JUMP_MS}ms linear both; mix-blend-mode: normal; }

/* 指す層：メインの舞台だけ。#stage.sp-point は指す層を選んだデッキでホバーできる端末、.sp-still は動きを止めたとき（強調は残し、浮き上がりだけ止める） */
#stage.sp-point [data-sp-hover] { transition: transform .2s ease, box-shadow .2s ease, opacity .2s ease; }
#stage.sp-point [data-sp-hover]:hover { transform: translateY(-4px) scale(1.04); box-shadow: 0 16px 40px rgba(31, 56, 100, .25); }
#stage.sp-point [data-sp-group]:hover > [data-sp-hover]:not(:hover) { opacity: .35; }
#stage.sp-point .sp-key-on { box-shadow: 0 0 0 4px rgba(255, 196, 0, .85); }
#stage.sp-point.sp-still [data-sp-hover] { transition: none; }
#stage.sp-point.sp-still [data-sp-hover]:hover { transform: none; }
#stage.sp-point [data-link] { cursor: pointer; }
.sp-light { position: fixed; left: 0; top: 0; z-index: 5; pointer-events: none; border-radius: 50%; display: none; mix-blend-mode: multiply;
  background: radial-gradient(circle closest-side, rgba(255, 214, 102, .38), rgba(255, 214, 102, .14) 55%, transparent 100%); }
.sp-light.sp-on { display: block; }

/* 書き込み：線の層 .sp-ink は舞台と同じ位置・同じ縮小に重ねる（舞台の中には何も足さない）。書き込みの間だけ入力を受ける */
.sp-ink { position: absolute; z-index: 20; pointer-events: none; touch-action: none; }
.sp-ink.sp-active { pointer-events: auto; cursor: crosshair; }
/* 追加ページの紙 .sp-paper：舞台と同じ位置・同じ縮小に重ねる白い紙（舞台の中には何も足さない）。線の層より下、舞台より上 */
.sp-paper { position: absolute; z-index: 15; display: none; background: #fff; }
.sp-side-blank, .sp-thumb-blank { position: absolute; left: 0; top: 0; right: 0; bottom: 0; display: flex; align-items: center; justify-content: center; color: #666; font: 14px/1 ${UI_FONT}; }
.sp-write-tools { position: fixed; top: 12px; right: 12px; z-index: 905; display: none; flex-direction: column; gap: 6px; padding: 6px; border-radius: 10px;
  background: rgba(20, 24, 29, .88); font: 14px/1.2 system-ui, sans-serif; }
.sp-write-tools.sp-on { display: flex; }
.sp-write-row { display: flex; align-items: center; gap: 6px; }
.sp-write-group { display: inline-flex; align-items: center; gap: 3px; padding: 2px 3px; border-radius: 8px; background: rgba(255, 255, 255, .06); color: #fff; }
.sp-write-label { margin: 0 2px 0 6px; }
.sp-write-tools button, .sp-write-pop button { padding: 6px 10px; border: 1px solid rgba(255, 255, 255, .25); border-radius: 6px; background: transparent; color: #fff; cursor: pointer; font: inherit; }
.sp-write-row > i { width: 1px; height: 22px; margin: 0 3px; background: rgba(255, 255, 255, .25); }
.sp-write-tools .sp-write-sample { display: inline-flex; align-items: center; gap: 3px; padding: 3px 5px; }
.sp-write-tools .sp-write-sample span { font-size: 9px; opacity: .8; }
.sp-write-tools button[aria-pressed="true"], .sp-write-pop button[aria-pressed="true"] { border-color: #fff; background: rgba(255, 255, 255, .16); }
.sp-write-tools [data-shape]::after { content: '🔒'; margin-left: 2px; font-size: 11px; visibility: hidden; }
.sp-write-tools button.sp-lock { border-color: #fff; background: #1b9bd1; }
.sp-write-tools button.sp-lock::after { visibility: visible; }
.sp-write-pop { position: fixed; z-index: 906; display: none; flex-direction: column; gap: 8px; padding: 10px; border-radius: 10px; background: #2a3038; color: #fff;
  box-shadow: 0 6px 20px rgba(0, 0, 0, .4); font: 13px/1.2 system-ui, sans-serif; }
.sp-write-pop.sp-on { display: flex; }
.sp-write-cols { display: grid; grid-template-columns: repeat(3, 30px); gap: 8px; }
.sp-write-pop .sp-write-cols button { width: 30px; height: 30px; padding: 0; border-radius: 50%; border-color: rgba(255, 255, 255, .35); }
.sp-write-pop .sp-write-cols button[aria-pressed="true"] { outline: 3px solid #fff; outline-offset: 2px; background-clip: padding-box; }
.sp-write-cap { color: #9fb3c8; font-size: 12px; margin-bottom: -4px; }
.sp-write-opts { display: flex; gap: 6px; }
.sp-write-opts button { min-width: 44px; }
.sp-write-tools [data-shape] { font-size: 18px; }
.sp-write-mini { position: fixed; z-index: 907; display: none; align-items: center; gap: 4px; padding: 5px 6px; border-radius: 8px; background: rgba(20, 24, 29, .94); box-shadow: 0 3px 10px rgba(0, 0, 0, .3); font: 13px/1.2 system-ui, sans-serif; }
.sp-write-mini.sp-on { display: flex; }
.sp-write-mini button { display: inline-flex; align-items: center; justify-content: center; height: 28px; min-width: 28px; padding: 0 6px; border: 1px solid rgba(255, 255, 255, .25); border-radius: 6px; background: transparent; color: #fff; cursor: pointer; font: inherit; }
.sp-write-mini button[aria-pressed="true"] { border-color: #fff; background: rgba(255, 255, 255, .18); }
.sp-write-mini .sp-write-dot { width: 22px; min-width: 22px; height: 22px; padding: 0; border-radius: 50%; border-color: rgba(255, 255, 255, .4); }
.sp-write-mini .sp-write-dot[aria-pressed="true"] { outline: 2px solid #fff; outline-offset: 2px; }
.sp-write-mini i { width: 1px; height: 22px; margin: 0 3px; background: rgba(255, 255, 255, .25); }
.sp-write-text { position: fixed; z-index: 907; min-width: 120px; margin: 0; padding: 0; border: 1px dashed #7fb6ff; outline: none; background: transparent; resize: none; overflow: hidden; line-height: 1.4; font-family: system-ui, "Hiragino Sans", "Meiryo", sans-serif; }

/* PDF の書き出し：印刷用の入れ物 .sp-print（body の直下に1つ）。画面には見えないが、配置はされる（display: none にしない。
   display: none の中では字体や CSS の画像の読み込みが始まらない）。1スライド＝1ページ（1920×1080）で、描画先は縮めない */
.sp-print { position: fixed; left: 0; top: 0; width: ${STAGE_W}px; z-index: -1; visibility: hidden; pointer-events: none; }
.sp-print-ink { position: absolute; left: 0; top: 0; width: ${STAGE_W}px; height: ${STAGE_H}px; }
.sp-print-page { position: relative; width: ${STAGE_W}px; height: ${STAGE_H}px; overflow: hidden; }
`;

  // 印刷の指定（@page と @media print）は、デッキだけに入れる。目次のページには入れない（目次の ⌘P は今のまま）
  const PRINT_CSS = `
@page { size: ${STAGE_W}px ${STAGE_H}px; margin: 0; }
@media print {
  html, body { overflow: visible !important; height: auto !important; background: #fff !important; }
  body > *:not(.sp-print) { display: none !important; }
  .sp-paper { display: none !important; }
  .sp-print { position: static; visibility: visible; }
  .sp-print-page { break-after: page; }
  .sp-print-page:last-child { break-after: auto; }
  .sp-print .sp-target, .sp-print .sp-print-ink { position: absolute; left: 0; top: 0; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  .sp-print-blank { background: #fff; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
}
`;
  function installPrintStyle() {
    if (document.querySelector('style.sp-print-style')) return;
    const style = document.createElement('style');
    style.className = 'sp-print-style';
    style.textContent = PRINT_CSS;
    document.head.appendChild(style);
  }

  // ---- 中身のスライドの並びの正規化 ----

  // ID が約束の形（REF_RE）の文字列か。ID でない値（undefined など）は、REF_RE.test に渡すと文字にされて通ってしまうので、型も見る
  const isRef = id => typeof id === 'string' && REF_RE.test(id);

  // 中身のスライドの並びを、プレイヤーが使う形にそろえた写しにする（中身のデータは書き換えない。約束 §3.2）。
  //   steps：0 以上の整数（ない・数でない・負なら 0、小数は切り捨て）
  //   ID が約束の形でないもの・重複したものは、console.warn で知らせる（動きは止めない）
  function normalizeSlides(list) {
    const first = new Map();                                     // ID → 最初に出てきた位置
    return list.map((raw, i) => {
      const s = raw && typeof raw === 'object' ? raw : {};
      const n = s.steps;
      const steps = typeof n === 'number' && Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
      if (!isRef(s.id)) {
        console.warn(`プレイヤー：${i + 1} 枚目のスライドの ID「${String(s.id)}」が約束の形（英字で始まり、英数字・-・_ だけ）ではありません。直近の場所には記録しません`);
      } else if (first.has(s.id)) {
        console.warn(`プレイヤー：スライドの ID「${s.id}」が重複しています（${first.get(s.id) + 1} 枚目と ${i + 1} 枚目）`);
      } else {
        first.set(s.id, i);
      }
      return { ...s, steps };
    });
  }

  // デッキが選ぶ動きの層（info.motion）を、プレイヤーが使う形にそろえる。
  //   send：送り（切り替えの動き）。既定は true（今と同じ）。entry：入場の型 'ppt'・'meiji'、既定は null（なし）。point：指す層、既定は false。
  //   ない項目は既定。形の違う項目は選んでいない扱い（既定）にし、console.warn で1回だけ知らせる（動きは止めない）
  function normalizeDeckMotion(raw) {
    const out = { send: true, entry: null, point: false };
    if (raw == null) return out;
    if (typeof raw !== 'object' || Array.isArray(raw)) {
      console.warn('プレイヤー：info.motion はオブジェクトで書いてください。動きの層は選んでいない扱いにします');
      return out;
    }
    const bad = [];
    if ('send' in raw) { if (typeof raw.send === 'boolean') out.send = raw.send; else bad.push('send'); }
    if ('entry' in raw) { if (raw.entry === null || ENTRY_STYLES.includes(raw.entry)) out.entry = raw.entry; else bad.push('entry'); }
    if ('point' in raw) { if (typeof raw.point === 'boolean') out.point = raw.point; else bad.push('point'); }
    if (bad.length) console.warn(`プレイヤー：info.motion の ${bad.join('・')} の値が読めないので、選んでいない扱いにします`);
    return out;
  }

  // ---- hash の読み書き（約束 §3.4）。DOM に触れない関数 ----

  // hash を読む。結果：{kind: "none"} | {kind: "ok", index, step} | {kind: "bad"}
  //   ""・"#"：none。「ID」「ID.段階」：その ID（なければ bad）。「1 から数えた位置」「位置.段階」：旧形式（範囲の外は bad）
  //   段階は 0〜steps にそろえる（大きければ steps）。壊れたパーセント表記・それ以外の形：bad
  function parseHash(hash, slides) {
    hash = String(hash);
    if (hash === '' || hash === '#') return { kind: 'none' };
    if (hash[0] !== '#') return { kind: 'bad' };
    let text;
    try { text = '#' + decodeURIComponent(hash.slice(1)); } catch (e) { return { kind: 'bad' }; }
    const clampStep = (digits, steps) => (digits === undefined ? 0 : Math.min(parseInt(digits, 10), steps));
    let m = /^#([A-Za-z][A-Za-z0-9_-]*)(?:\.(\d+))?$/.exec(text);
    if (m) {
      const index = slides.findIndex(s => s.id === m[1]);
      return index < 0 ? { kind: 'bad' } : { kind: 'ok', index, step: clampStep(m[2], slides[index].steps) };
    }
    m = /^#(\d+)(?:\.(\d+))?$/.exec(text);
    if (m) {
      const index = parseInt(m[1], 10) - 1;
      return index < 0 || index >= slides.length ? { kind: 'bad' } : { kind: 'ok', index, step: clampStep(m[2], slides[index].steps) };
    }
    return { kind: 'bad' };
  }

  // 段階 0 なら「#ID」、それ以外は「#ID.段階」
  const formatHash = (id, step) => (step === 0 ? '#' + id : '#' + id + '.' + step);

  // ---- 知らせ ----
  let toastEl = null, toastTimer = 0;
  let toastAvoid = null;                                         // 知らせが避ける要素（操作ボタンの帯。startDeck が登録する）
  let toastLift = null;                                          // 知らせを持ち上げる高さ () => px（メモの帯の高さ。startDeck が登録する）
  let toastArea = null;                                          // 知らせを置く横の範囲 () => {left, width}（デッキの中央の領域。startDeck が登録する。目次は null で画面全体）

  // 知らせの置き場所。操作ボタンの帯が出ているときは、帯の高さを測って、その上に置く（帯が2段・3段になっても重ならない）。
  // 帯の出入り・画面の大きさやノートの開閉で帯の高さが変わったときも、呼び直す
  function placeToast() {
    if (!toastEl) return;
    let bottom = TOAST_BOTTOM_PX + (toastLift ? toastLift() : 0);
    if (toastAvoid && toastAvoid.classList.contains('sp-on')) {
      bottom = Math.max(bottom, window.innerHeight - toastAvoid.getBoundingClientRect().top + TOAST_GAP_PX);
    }
    toastEl.style.bottom = bottom + 'px';
    if (toastArea) {                                             // 左の列とノートを除いた中央の領域の真ん中に置く。外寸（padding 込み）が画面の中に収まるよう、中心を寄せる
      const area = toastArea(), vw = window.innerWidth;
      toastEl.style.width = 'max-content';                       // left を動かしても折り返しが変わらないように（絶対配置の幅は left の残りで決まる）
      toastEl.style.maxWidth = Math.min(vw - 16, Math.max(160, Math.min(vw * 0.8, 640, area.width - 16))) + 'px';
      const half = toastEl.getBoundingClientRect().width / 2;
      const centre = Math.max(8 + half, Math.min(vw - 8 - half, area.left + area.width / 2));
      toastEl.style.left = centre + 'px';
    }
  }

  function toast(message) {
    if (!toastEl || !toastEl.isConnected) {
      toastEl = document.createElement('div');
      toastEl.className = 'sp-toast';
      toastEl.setAttribute('role', 'status');
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = message;
    placeToast();
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.remove(); toastEl = null; }, TOAST_MS);
  }

  // ---- キー操作の共通の決まり ----
  const isTyping = t => !!t && t.nodeType === 1 && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  // 修飾キー付き・変換中・入力欄の中のキーは、プレイヤーが扱わない
  const ignoredKey = e => e.ctrlKey || e.altKey || e.metaKey || e.isComposing || isTyping(e.target);

  // ---- 画面の部品の共通の道具 ----

  // 文字は textContent で入れる（HTML として解釈しない。約束 §2.3）
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // プレイヤーのボタン。マウス・タッチで押したあとは焦点を外す（焦点が残ると、次の Space がボタンをもう一度押してしまう）。
  // キーボードで押したとき（e.detail === 0）は、焦点を残す
  function makeButton(label, run) {
    const b = el('button', 'sp-btn', label);
    b.type = 'button';
    b.addEventListener('click', e => {
      if (e.detail > 0) b.blur();
      run();
    });
    return b;
  }

  // Space・Enter で押されるのは、焦点が乗ったプレイヤーのボタン自身（スライドの移動と二重にしない）。
  // プレイヤーのボタンは makeButton で作る（class sp-btn）。どの部品の中にあっても同じに扱う
  const isOwnButton = t => !!t && t.nodeType === 1 && t.tagName === 'BUTTON' && t.classList.contains('sp-btn');

  // 背景（重なりの外側）を押すと閉じる。中の文字を選ぼうとして、外で離しただけでは閉じない
  function closeOnBackdrop(root, close) {
    let downOnBackdrop = false;
    root.addEventListener('mousedown', e => { downOnBackdrop = e.target === root; });
    root.addEventListener('click', e => { if (downOnBackdrop && e.target === root) close(); });
  }

  // 設定。読み書きは try/catch で囲み、使えなくてもこのページの中の値で動く。形が違う項目（壊れた JSON は全項目）は捨てて既定にする。
  // motion（動き。真偽、既定は true）・light（光。真偽、既定は true）・memo（メモの帯。真偽、既定は false）は、利用者が選ぶ（または保存されている）までは value に入れない：保存する値にも入らない
  const settings = (() => {
    const fallback = () => ({ controls: 'auto', notes: false });
    // 項目ごとに確かめ、壊れた項目だけ既定に戻す（{"controls":"always"} なら controls だけ生かす）
    function parse(text) {
      const value = fallback();
      if (typeof text !== 'string') return value;
      let v;
      try { v = JSON.parse(text); } catch (e) { return value; }
      if (!v || typeof v !== 'object') return value;
      if (CONTROLS_MODES.includes(v.controls)) value.controls = v.controls;
      if (typeof v.notes === 'boolean') value.notes = v.notes;
      if (typeof v.motion === 'boolean') value.motion = v.motion;
      if (typeof v.side === 'boolean') value.side = v.side;
      if (typeof v.light === 'boolean') value.light = v.light;
      if (typeof v.memo === 'boolean') value.memo = v.memo;
      if (v.ink && typeof v.ink === 'object') {                  // 書き込みの種類ごとの色・太さ・大きさ・描き味。値ごとに確かめ、壊れた値はその値だけ捨てる
        const ink = {};
        for (const kind of WRITE_KINDS) {
          const s = v.ink[kind];
          if (!s || typeof s !== 'object') continue;
          const o = {};
          if (WRITE_COLORS.includes(s.c)) o.c = s.c;
          if ((kind === 'text' ? WRITE_SIZES : WRITE_WIDTHS).some(([, n]) => n === s.w)) o.w = s.w;
          if (kind === 'free' && WRITE_FEELS.some(([, n]) => n === s.r)) o.r = s.r;
          if (Object.keys(o).length) ink[kind] = o;
        }
        if (Object.keys(ink).length) value.ink = ink;
      }
      return value;
    }
    let value = fallback();
    return {
      load() {
        let text = null;
        try { text = window.localStorage.getItem(SETTINGS_KEY); } catch (e) { /* 読めなければ既定 */ }
        value = parse(text);
      },
      get: () => ({ motion: true, side: false, light: true, memo: false, ...value }),
      set(patch) {
        value = { ...value, ...patch };
        try { window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(value)); } catch (e) { /* 書けなくても、このページの中では効く */ }
      },
    };
  })();

  // 重なり（操作の一覧など）の積み重ね。一番上の重なりが、キーを先に受ける。ノートは数えない（ほかの重なりと同時に開くため）。
  //   重なり：{name, modal, close(), onKey(e)}。onKey が true を返したキーは、それ以上扱わない。
  //   modal の重なりが一番上にあるとき、? Esc N F 以外のキーではスライドを動かさない（O・L・H も効かない。
  //   縮小一覧やリンクの表示の中で O・L を押して閉じたいときは、その重なりの onKey で受ける）。
  //   modal の重なりには、共通の動きが付く：Tab は重なりの中（push に渡した root の中）だけを巡り、
  //   閉じたとき（remove）は、開く前に焦点があった要素へ焦点を戻す。
  //   縮小一覧（O）・操作の一覧（?）・リンクを表示（L）・補足の窓（more）は、ここに足す
  const overlays = (() => {
    const stack = [];
    // 焦点が当たる部品（重なりの中の Tab の巡り先）。描画先（.sp-target）の中は巡らない
    const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    return {
      // 開く。root：重なりの要素。開く前に焦点があった要素を覚える（push のあとで、重なりの中へ焦点を移す）
      push(o, root) {
        if (stack.includes(o)) return;
        o.root = root || null;
        o.opener = document.activeElement;
        stack.push(o);
      },
      // 閉じる。焦点が重なりの中にあった・どこにもなかったときだけ、開く前の要素へ戻す（要素が消えていれば戻さない）
      remove(o) {
        const i = stack.indexOf(o);
        if (i < 0) return;
        stack.splice(i, 1);
        const { opener, root } = o;
        o.opener = o.root = null;
        const active = document.activeElement;
        const lost = !active || active === document.body || (root && root.contains(active));
        if (lost && opener && opener !== document.body && opener.isConnected && typeof opener.focus === 'function') opener.focus({ preventScroll: true });
      },
      top: () => stack[stack.length - 1] || null,
      name: () => (stack.length ? stack[stack.length - 1].name : 'none'),
      // Tab・Shift＋Tab：重なりの中の部品だけを巡る（端で反対の端へ）。焦点が中になければ、最初（Shift なら最後）へ
      trapTab(o, e) {
        const items = o.root ? Array.from(o.root.querySelectorAll(FOCUSABLE)).filter(n => !n.closest('.sp-target, [inert]') && n.getClientRects().length > 0) : [];
        if (!items.length) return;
        const i = items.indexOf(document.activeElement);
        const next = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : (i < 0 || i === items.length - 1 ? 0 : i + 1);
        items[next].focus();
      },
    };
  })();

  // 重なりから呼ぶ動き。縮小一覧（O）とリンクを表示（L）は startDeck が入れる
  const commands = { overview: null, links: null };

  // 操作の一覧（?）の共通の部品（デッキと目次が使う）。.sp-help：キーの一覧を出す modal の重なり（背景を押すと閉じる）。
  //   opts.rows：キーの一覧 [[キーの文字の配列, 説明], ...]
  //   opts.extra(panel)：キーの一覧の下に足す部品（デッキは操作ボタンの出し方）。なくてもよい
  //   opts.onChange(open)：開いた・閉じたときの知らせ（デッキは操作ボタンの印を変える）。なくてもよい
  //   opts.beforeOpen()：開く前に呼ぶ（デッキは動きを終わらせる settleMotion。目次には動きがない）。なくてもよい
  //   戻り値：{open, close, toggle, element()}（element：開いていればその要素、閉じていれば null）
  function createHelp(opts) {
    let helpEl = null;
    const overlay = { name: 'help', modal: true, close };
    function open() {
      if (helpEl) return;
      if (opts.beforeOpen) opts.beforeOpen();
      helpEl = el('div', 'sp-help');
      helpEl.setAttribute('role', 'dialog');
      helpEl.setAttribute('aria-modal', 'true');
      helpEl.setAttribute('aria-label', '操作の一覧');
      const panel = el('div', 'sp-help-panel');
      panel.tabIndex = -1;
      panel.appendChild(el('div', 'sp-help-title', '操作の一覧'));
      for (const [keys, text] of opts.rows) {
        const row = el('div', 'sp-help-row');
        const cell = el('span', 'sp-help-keys');
        for (const k of keys) cell.appendChild(el('kbd', 'sp-key', k));
        row.append(cell, el('span', 'sp-help-text', text));
        panel.appendChild(row);
      }
      if (opts.extra) opts.extra(panel);
      const closeRow = el('div', 'sp-help-close');
      closeRow.appendChild(makeButton('閉じる', close));
      panel.appendChild(closeRow);
      helpEl.appendChild(panel);
      closeOnBackdrop(helpEl, close);
      document.body.appendChild(helpEl);
      overlays.push(overlay, helpEl);                            // 焦点を移す前に呼ぶ（開く前の焦点を覚える）
      if (opts.onChange) opts.onChange(true);
      panel.focus({ preventScroll: true });
    }
    function close() {
      if (!helpEl) return;
      helpEl.remove();
      helpEl = null;
      overlays.remove(overlay);
      if (opts.onChange) opts.onChange(false);
    }
    return { open, close, toggle: () => (helpEl ? close() : open()), element: () => helpEl };
  }

  // 指で払う操作の見分け（デッキと目次が使う）。払った向き 'left'|'right'|'up'|'down' を opts.onSwipe(dir) に渡す。
  //   opts.onStart()：払いになるかもしれない指が触れたとき（扱う所で始めたときだけ）に呼ぶ。デッキは、この時点の操作ボタンの帯の出入りを覚える
  //   見分けるのは指の入力（pointerType が touch）だけ。ペンは書き込み（D）に使い、マウスはキーと同じ操作を持つため扱わない。
  //   opts.enabled()：払いを扱うか（なければいつも扱う）。デッキはペンの間 false にする
  //   判定は指を離したとき（pointerup）に1回。途中の動き（pointermove）は見ない：始点と終点だけで決まる。
  //   動きそのものは持たない。呼ぶ側が、同じ向きのキーと同じ関数を呼ぶ（SWIPE_KEYS）
  function createSwipe(opts) {
    let track = null;                                            // 払いかもしれない今の指 {id, x, y, t, target}。扱わない所で始めた・取りやめたときは null
    const zoomed = () => !!window.visualViewport && window.visualViewport.scale > SWIPE_ZOOM_SCALE;

    // 始めた所が扱わない所か：画面の端、プレイヤーの部品、入力の部品、重なりが開いている間、拡大している間。
    // リンク・カードの上は扱う（払いではブラウザはクリックを起こさない。大きなリンクの箱がスライドの大半を占めても払えるように）
    function startsOnExcluded(e) {
      const nearEdge = e.clientX <= SWIPE_EDGE_PX || e.clientY <= SWIPE_EDGE_PX
        || e.clientX >= window.innerWidth - SWIPE_EDGE_PX || e.clientY >= window.innerHeight - SWIPE_EDGE_PX;
      if (nearEdge || zoomed() || overlays.top()) return true;
      // 知らせは pointer-events: none（クリックを下へ通す）なので、指を置いてもイベントの相手は下のスライドや html になり、
      // closest(SWIPE_UI) に当たらない。そこで相手ではなく、指を置いた点が表示中の知らせの矩形に入るかで見る。
      // 知らせは表示の間だけ DOM にあるため、矩形は pointerdown のたびに調べる（帯が出て知らせの位置が動く前の値になる）
      if (toastEl && toastEl.isConnected) {
        const r = toastEl.getBoundingClientRect();
        if (e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom) return true;
      }
      const node = e.target && e.target.nodeType === 1 ? e.target : null;
      return !!node && (isTyping(node) || !!node.closest(SWIPE_UI));
    }

    // 始めた要素から上へ、払いの向き（horizontal：横）にスクロールできる要素（overflow が auto・scroll で、実際にはみ出している）があるか。
    // 端まで来ていても同じに扱う（そこでブラウザが払いを取るかどうかは、中身の側の都合なので）
    function scrollsAlong(node, horizontal) {
      for (let n = node; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
        const cs = window.getComputedStyle(n);
        const overflow = horizontal ? cs.overflowX : cs.overflowY;
        if ((overflow === 'auto' || overflow === 'scroll') && (horizontal ? n.scrollWidth > n.clientWidth : n.scrollHeight > n.clientHeight)) return true;
      }
      return false;
    }

    const selecting = () => { const sel = window.getSelection && window.getSelection(); return !!sel && String(sel) !== ''; };

    document.addEventListener('pointerdown', e => {
      if (e.pointerType !== 'touch') return;
      track = null;                                              // 2本目以降の指（isPrimary でない）と、前の払いの残りは、ここで取りやめる
      if (opts.enabled && !opts.enabled()) return;               // 払いを扱わない間（デッキはペンの間）
      if (!e.isPrimary || startsOnExcluded(e)) return;
      if (opts.onStart) opts.onStart();
      track = { id: e.pointerId, x: e.clientX, y: e.clientY, t: e.timeStamp, target: e.target };
    }, { capture: true, passive: true });

    document.addEventListener('pointerup', e => {
      const t = track;
      if (e.pointerType !== 'touch' || !t || t.id !== e.pointerId) return;
      track = null;
      const dx = e.clientX - t.x, dy = e.clientY - t.y;
      const horizontal = Math.abs(dx) >= Math.abs(dy);
      const major = horizontal ? Math.abs(dx) : Math.abs(dy), minor = horizontal ? Math.abs(dy) : Math.abs(dx);
      const need = Math.max(SWIPE_MIN_PX, (horizontal ? window.innerWidth : window.innerHeight) * SWIPE_MIN_RATIO);
      if (major < need || major < minor * SWIPE_DIRECTION_RATIO || e.timeStamp - t.t > SWIPE_MAX_MS) return;
      if (zoomed() || overlays.top() || selecting() || scrollsAlong(t.target, horizontal)) return;
      opts.onSwipe(horizontal ? (dx < 0 ? 'left' : 'right') : (dy < 0 ? 'up' : 'down'));
    }, { capture: true, passive: true });

    document.addEventListener('pointercancel', e => {
      if (track && track.id === e.pointerId) track = null;      // ブラウザが指の入力を取った（スクロール・拡大など）
    }, { capture: true, passive: true });

    // 拡大している間は touch-action を外し（CSS の sp-zoomed）、拡大した画面を指で動かせるようにする
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', () => document.documentElement.classList.toggle('sp-zoomed', zoomed()));
    }
  }

  // F：全画面にする。もう全画面なら抜ける。使えないとき・許可されないときは知らせる
  // 入場。メインの舞台 stage の役目の印から動きを作る。
  //   arm(style)：入場すると決めた時点（描く前）に呼ぶ。state を 'pending' にする（送りの動きの間も、入場を待っていると分かるように）
  //   prepare(style)：描いた直後に呼ぶ。いま見えている印（段階で隠れているものは除く）を文書の順に集め、動きを作って止めておく
  //     （fill: backwards で入る前の姿になる。送りの動きの新しい画面にも、この姿が写る）。戻り値は番号（play に渡す）。対象がなければ 0
  //   play(id)：止めておいた動きを再生する。id が今の番号でなければ何もしない（古い送りの動きの終わりが、新しいスライドを動かさない）
  //   settle()：入場の途中の状態だけを終える（動き終わりの姿にし、数え上げの文字を戻す）。書き込みや押す仕掛けには触れない。何度呼んでもよい
  //   reset()：settle して、入場なし（state 'none'）にする（入場しない移動のとき）
  //   info()：{state, style, count, effects, plannedMs}。state は 'none'|'pending'|'playing'|'done'|'settled'
  //   active()：入場の途中（pending・playing）か
  //   done()：入場が終わる（done・settled・none になる）と解決する Promise
  //   onEnd()：入場が終わった（done・settled）ときに呼ぶ（デッキはリンクの印を置き直す。動いている間の位置で置いたため）
  // どこで例外が出ても settle して止まった姿に戻す
  function createEntry(stage, onEnd) {
    let state = 'none', style = null, plan = [], plannedMs = 0, id = 0, raf = 0;
    let waiters = [];
    const finished = () => state === 'none' || state === 'done' || state === 'settled';
    function wake() { if (!finished()) return; const w = waiters; waiters = []; w.forEach(r => r()); }
    function ended() { wake(); if (onEnd) { try { onEnd(); } catch (e) { /* 印の置き直しに失敗しても、入場は終わっている */ } } }

    // 数え上げ：文字の先頭の数（-、桁区切りの ,、小数点を含む）を 0 から数える。数がなければ null
    function parseCount(text) {
      const m = /^(\D*?)(-?\d[\d,]*(?:\.\d+)?)([\s\S]*)$/.exec(text);
      if (!m) return null;
      const num = m[2], dec = (num.split('.')[1] || '').length;
      return { prefix: m[1], to: Number(num.replace(/,/g, '')), dec, sep: num.includes(','), suffix: m[3] };
    }
    const formatCount = (c, v) => c.prefix + (c.sep
      ? v.toLocaleString('en-US', { minimumFractionDigits: c.dec, maximumFractionDigits: c.dec })
      : v.toFixed(c.dec)) + c.suffix;

    function restoreTexts() { for (const p of plan) if (p.text != null) p.e.textContent = p.text; }
    function tick() {
      raf = 0;
      if (state !== 'playing') return;
      for (const p of plan) {
        if (!p.count) continue;
        const t = Math.min(Math.max(((p.a.currentTime || 0) - p.delay) / p.duration, 0), 1);
        p.e.textContent = t >= 1 ? p.text : formatCount(p.count, p.count.to * t);
      }
      raf = requestAnimationFrame(tick);
    }

    function settle() {
      if (finished()) return;
      id++;
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      for (const p of plan) { try { p.a.finish(); } catch (e) { /* 終われなくても、下で外す */ } try { p.a.cancel(); } catch (e) { /* 外せなければそのまま */ } }
      restoreTexts();
      state = 'settled';
      ended();
    }
    function reset() { settle(); state = 'none'; plan = []; style = null; plannedMs = 0; wake(); }
    function arm(nextStyle) { reset(); if (ENTRY_EFFECTS[nextStyle]) { style = nextStyle; state = 'pending'; } }
    function fail(e) { console.warn('プレイヤー：入場の動きで例外が出たので、止まった姿にしました', e); settle(); }

    function prepare(nextStyle) {
      if (!(state === 'pending' && !plan.length && style === nextStyle)) reset();     // arm した入場なら、その続き
      const table = ENTRY_EFFECTS[nextStyle];
      const none = () => { reset(); return 0; };
      if (!table || !Element.prototype.animate) return none();
      try {
        const targets = Array.from(stage.querySelectorAll('[data-sp-role]'))
          .filter(e => table[e.getAttribute('data-sp-role')] && window.getComputedStyle(e).visibility === 'visible');
        if (!targets.length) return none();
        const effects = targets.map(e => table[e.getAttribute('data-sp-role')]);
        const longest = Math.max(...effects.map(f => ENTRY_MS[f]));
        const gap = targets.length > 1 ? Math.max(0, Math.min(ENTRY_GAP_MS, (ENTRY_TARGET_MS - longest) / (targets.length - 1))) : 0;
        state = 'pending';                                       // 途中で失敗したら settle が、作った分を片付ける
        targets.forEach((e, i) => {
          let effect = effects[i];
          const count = effect === 'count' ? parseCount(e.textContent) : null;
          if (effect === 'count' && !count) effect = 'fade';
          const p = { e, effect, delay: i * gap, duration: ENTRY_MS[effect], count, text: count ? e.textContent : null };
          p.a = e.animate(ENTRY_KEYFRAMES[effect], { duration: p.duration, delay: p.delay, easing: ENTRY_EASING, fill: 'backwards' });
          plan.push(p);                                          // 作ったらすぐ足す（次の animate で例外が出ても、これは片付く）
          p.a.pause();
          if (count) e.textContent = formatCount(count, 0);
        });
        plannedMs = Math.min(ENTRY_MAX_MS, Math.max(...plan.map(p => p.delay + p.duration)));
        style = nextStyle;
        return ++id;
      } catch (e) {
        fail(e);
        return 0;
      }
    }

    function play(which) {
      if (which !== id || state !== 'pending') return;
      try {
        state = 'playing';
        for (const p of plan) p.a.play();
        const mine = id;
        Promise.all(plan.map(p => p.a.finished)).then(() => {
          if (mine !== id || state !== 'playing') return;
          if (raf) { cancelAnimationFrame(raf); raf = 0; }
          for (const p of plan) { try { p.a.cancel(); } catch (e) { /* 外せなければそのまま */ } }
          restoreTexts();
          state = 'done';
          ended();
        }, err => {
          // 今の回の動きが、外から取り消された・失敗した：止まった姿に戻す。
          // settle・reset で終えた回（番号が進んでいる）の失敗は、もう片付いているので何もしない
          if (mine === id && state === 'playing') fail(err);
        });
        if (plan.some(p => p.count)) raf = requestAnimationFrame(tick);
      } catch (e) {
        fail(e);
      }
    }

    return {
      arm, prepare, play, settle, reset,
      active: () => state === 'pending' || state === 'playing',
      info: () => ({ state, style, count: plan.length, effects: plan.map(p => p.effect), plannedMs }),
      done: () => (finished() ? Promise.resolve() : new Promise(r => waiters.push(r))),
    };
  }

  // 指す層。メインの舞台 stage にだけ効く。
  //   opts.point()：指す層を選んだデッキで、ホバーできる端末か。opts.still()：動きを止めているか（浮き上がりと揺れを止める）
  //   opts.light()：いま光を出してよいか（光の設定・modal の重なり・ペンの間を見る）。opts.scale()：舞台の縮小の倍率
  //   refresh()：舞台の class（sp-point・sp-still）を付け直す。hide()：光を消す（重なりを開くとき・ペンを始めるとき）
  //   lightActive()：光を出せる状態か（操作ボタンの帯の出し方が使う）
  // 関係するもの（同じ data-sp-key）は一緒に sp-key-on。押せるもの（data-link）は、乗せるとその印が小さく揺れる
  function createPointer(stage, opts) {
    let light = null;                                            // 光の要素（指す層のデッキで、初めて出すときに作る。ほかのデッキの DOM は変えない）
    const on = () => stage.classList.contains('sp-point');
    function hide() { if (light) light.classList.remove('sp-on'); }
    // 指す層のないデッキの舞台には、class を何も足さない（sp-still も sp-point の下でだけ使う）
    function refresh() {
      const point = opts.point();
      stage.classList.toggle('sp-point', point);
      stage.classList.toggle('sp-still', point && opts.still());
      if (!point) { hide(); clearKeys(); }
    }
    function clearKeys() { for (const e of stage.querySelectorAll('.sp-key-on')) e.classList.remove('sp-key-on'); }
    stage.addEventListener('mouseover', e => {
      if (!on()) return;
      const keyed = e.target.closest && e.target.closest('[data-sp-key]');
      clearKeys();
      if (keyed && stage.contains(keyed)) {
        const key = keyed.getAttribute('data-sp-key');
        for (const k of stage.querySelectorAll('[data-sp-key]')) if (k.getAttribute('data-sp-key') === key) k.classList.add('sp-key-on');
      }
      const link = e.target.closest && e.target.closest('[data-link]');
      if (link && stage.contains(link) && !(e.relatedTarget && link.contains(e.relatedTarget)) && !opts.still()) {
        const n = link.getAttribute('data-link');
        const mark = Array.from(document.querySelectorAll('.sp-linkmark')).find(m => m.dataset.index === n);
        if (mark && mark.animate) { try { mark.animate(LINK_WIGGLE, { duration: 500, easing: 'ease-in-out' }); } catch (err) { /* 揺れなくても押せる */ } }
      }
    });
    stage.addEventListener('mouseleave', clearKeys);
    const lightActive = () => on() && opts.light();
    document.addEventListener('pointermove', e => {
      if (e.pointerType !== 'mouse' || !lightActive()) { hide(); return; }
      const r = stage.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) { hide(); return; }
      if (!light) {
        light = el('div', 'sp-light');
        light.setAttribute('aria-hidden', 'true');
        document.body.appendChild(light);
      }
      const size = LIGHT_RADIUS * 2 * opts.scale();
      Object.assign(light.style, { width: size + 'px', height: size + 'px', transform: `translate(${e.clientX - size / 2}px, ${e.clientY - size / 2}px)` });
      light.classList.add('sp-on');
    }, { passive: true });
    document.addEventListener('pointerleave', hide);
    return { refresh, hide, lightActive };
  }

  // ---- 書き込みの形の計算と描画。舞台の座標（STAGE_W×STAGE_H）で扱う ----
  const wDist = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]);
  const wPathLen = pts => pts.reduce((s, p, i) => (i ? s + wDist(pts[i - 1], p) : 0), 0);
  // 点を WRITE_STEP ごとに取り直す（速く描いても遅く描いても、同じに判定する）
  function wResample(pts) {
    const out = [pts[0]];
    let [px, py] = pts[0];
    for (let i = 1; i < pts.length; i++) {
      const [x, y] = pts[i];
      let d = Math.hypot(x - px, y - py);
      while (d >= WRITE_STEP) { const t = WRITE_STEP / d; px += (x - px) * t; py += (y - py) * t; out.push([px, py]); d = Math.hypot(x - px, y - py); }
    }
    const end = pts[pts.length - 1];
    if (out.length === 1 || wDist(end, out[out.length - 1]) > 0.5) out.push(end);
    return out;
  }
  // 前後 r 点の平均でならす（端に近いほど狭め。始めと終わりは動かさない）
  function wAverage(pts, r) {
    if (!r || pts.length < 3) return pts;
    return pts.map((p, i) => {
      const k = Math.min(r, i, pts.length - 1 - i);
      let sx = 0, sy = 0;
      for (let j = i - k; j <= i + k; j++) { sx += pts[j][0]; sy += pts[j][1]; }
      return [sx / (2 * k + 1), sy / (2 * k + 1)];
    });
  }
  function wBBox(pts) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [x, y] of pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }
  function wSegDist(p, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1], len2 = dx * dx + dy * dy;
    const t = len2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2)) : 0;
    return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
  }
  function wRdp(pts, eps) {
    if (pts.length < 3) return pts.slice();
    let best = 0, idx = 0;
    const a = pts[0], b = pts[pts.length - 1];
    for (let i = 1; i < pts.length - 1; i++) { const d = wSegDist(pts[i], a, b); if (d > best) { best = d; idx = i; } }
    if (best <= eps) return [a, b];
    return wRdp(pts.slice(0, idx + 1), eps).slice(0, -1).concat(wRdp(pts.slice(idx), eps));
  }
  const wPolyDist = (p, poly) => Math.min(...poly.map((q, i) => wSegDist(p, q, poly[(i + 1) % poly.length])));
  const wTriArea = (a, b, q) => Math.abs((b[0] - a[0]) * (q[1] - a[1]) - (q[0] - a[0]) * (b[1] - a[1])) / 2;

  // 取り直した点の列を、線か囲み（shape：'rect' か 'ellipse'）に当てはめる。どちらでもなければ null（手書きのまま）
  function wRecognize(pts, shape) {
    if (pts.length < 3) return null;
    const len = wPathLen(pts);
    if (len < 40) return null;
    const a = pts[0], b = pts[pts.length - 1], chord = wDist(a, b), bb = wBBox(pts), diag = Math.hypot(bb.w, bb.h) || 1;
    if (chord / wPathLen(wAverage(pts, 3)) > 0.9) {
      const dev = Math.max(...pts.map(p => wSegDist(p, a, b)));
      if (dev >= Math.max(10, chord * 0.06)) return null;
      const q = b.slice();
      const ang = Math.atan2(b[1] - a[1], b[0] - a[0]) * 180 / Math.PI, snap = Math.round(ang / 90) * 90;
      if (Math.abs(ang - snap) < 6) { if (snap % 180 === 0) q[1] = a[1]; else q[0] = a[0]; }   // 水平・垂直から 6° 以内はそろえる
      return { t: 'line', a: a.slice(), b: q, arrow: 0 };
    }
    if (chord > 0.22 * diag || len > diag * 4.2 || bb.w < 24 || bb.h < 24) return null;
    const n = pts.length;
    const rect = [[bb.x, bb.y], [bb.x + bb.w, bb.y], [bb.x + bb.w, bb.y + bb.h], [bb.x, bb.y + bb.h]];
    const errRect = pts.reduce((s, p) => s + wPolyDist(p, rect), 0) / n / diag;
    const cx = bb.x + bb.w / 2, cy = bb.y + bb.h / 2, rx = bb.w / 2, ry = bb.h / 2;
    const errEll = pts.reduce((s, p) => s + Math.abs(Math.hypot((p[0] - cx) / rx, (p[1] - cy) / ry) - 1) * Math.min(rx, ry), 0) / n / diag;
    let tri = null;
    const cand = wRdp(pts, diag * 0.08);
    for (let i = 0; i < cand.length; i++) for (let j = i + 1; j < cand.length; j++) for (let k = j + 1; k < cand.length; k++) {
      const area = wTriArea(cand[i], cand[j], cand[k]);
      if (!tri || area > tri.area) tri = { area, pts: [cand[i], cand[j], cand[k]] };
    }
    const errTri = tri ? pts.reduce((s, p) => s + wPolyDist(p, tri.pts), 0) / n / diag : Infinity;
    if (Math.min(errRect, errEll, errTri) > 0.07) return null;
    if (shape === 'rect') return { t: 'rect', x: bb.x, y: bb.y, w: bb.w, h: bb.h };
    let erx = rx, ery = ry;
    if (Math.abs(rx - ry) / Math.max(rx, ry) < 0.12) erx = ery = (rx + ry) / 2;           // ほぼ円は正円
    return { t: 'ellipse', cx, cy, rx: erx, ry: ery };
  }

  // 矢印の頭の三角の3点（描くのも選ぶのも同じ形）
  function wArrowTri(p, from, w) {
    const ang = Math.atan2(p[1] - from[1], p[0] - from[0]), len = 14 + w * 2.2;
    return [[p[0], p[1]],
      [p[0] - len * Math.cos(ang - 0.45), p[1] - len * Math.sin(ang - 0.45)],
      [p[0] - len * Math.cos(ang + 0.45), p[1] - len * Math.sin(ang + 0.45)]];
  }
  function wArrowHead(ctx, p, from, w) {
    const t = wArrowTri(p, from, w);
    ctx.beginPath();
    ctx.moveTo(t[0][0], t[0][1]);
    ctx.lineTo(t[1][0], t[1][1]);
    ctx.lineTo(t[2][0], t[2][1]);
    ctx.closePath();
    ctx.fill();
  }
  // 三角の中、または辺から tol 以内か
  function wInTri(q, t, tol) {
    const side = (a, b) => (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0]);
    const d = [side(t[0], t[1]), side(t[1], t[2]), side(t[2], t[0])];
    if (d.every(v => v >= 0) || d.every(v => v <= 0)) return true;
    return wSegDist(q, t[0], t[1]) < tol || wSegDist(q, t[1], t[2]) < tol || wSegDist(q, t[2], t[0]) < tol;
  }
  // 書き込みの1つを、舞台の座標の 2D の文脈に描く（画面と PDF で共通）
  function wPaintObject(ctx, o) {
    ctx.save();
    ctx.strokeStyle = ctx.fillStyle = o.color;
    ctx.lineWidth = o.width;
    ctx.lineCap = ctx.lineJoin = 'round';
    if (o.hl) ctx.globalAlpha = WRITE_HL.alpha;
    ctx.beginPath();
    if (o.t === 'free') {
      const pts = wAverage(o.pts, o.r);
      if (pts.length === 1) { ctx.arc(pts[0][0], pts[0][1], o.width / 2, 0, Math.PI * 2); ctx.fill(); }
      else {
        ctx.moveTo(pts[0][0], pts[0][1]);
        if (!o.r) for (const [x, y] of pts.slice(1)) ctx.lineTo(x, y);
        else {                                                   // 中点を通る2次曲線でつなぐ
          for (let i = 1; i < pts.length - 1; i++) ctx.quadraticCurveTo(pts[i][0], pts[i][1], (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2);
          ctx.lineTo(pts[pts.length - 1][0], pts[pts.length - 1][1]);
        }
        ctx.stroke();
      }
    } else if (o.t === 'line') {
      ctx.moveTo(o.a[0], o.a[1]);
      ctx.lineTo(o.b[0], o.b[1]);
      ctx.stroke();
      if (o.arrow === 1) wArrowHead(ctx, o.b, o.a, o.width);
      if (o.arrow === 2) wArrowHead(ctx, o.a, o.b, o.width);
    } else if (o.t === 'rect') ctx.strokeRect(o.x, o.y, o.w, o.h);
    else if (o.t === 'ellipse') { ctx.ellipse(o.cx, o.cy, o.rx, o.ry, 0, 0, Math.PI * 2); ctx.stroke(); }
    else if (o.t === 'text') {
      ctx.font = `${o.size}px ${UI_FONT}`;
      ctx.textBaseline = 'top';
      o.lines.forEach((s, i) => ctx.fillText(s, o.x, o.y + i * o.size * WRITE_LINE_H));
    }
    ctx.restore();
  }

  // 書き込み。線の層 .sp-ink（STAGE_W×STAGE_H の canvas）を舞台に重ねて書く。初めて使うときに作る（使わないデッキの DOM は変えない）。
  //   opts.stage：メインの舞台。opts.pageKey()：今のページのキー（ふつうのスライドは 's:' + ID。追加ページは 'a:' + 識別子）
  //   opts.onChange(active)：始めた・終えたときに呼ぶ。opts.styles：{get() → 保存された ink（なければ undefined）, set(ink)}
  //   opts.onUndoEmpty()：今のページに戻すものがないときの「ひとつ戻す」で呼ぶ（真を返せば、呼んだ側が扱った）
  //   書き込みは Map<ページのキー, {objs, undo}> に舞台の座標で覚える。保存しない（約束 §3.2）。objs の1つ：
  //     {t: 'free', pts, color, width, r, hl?}・{t: 'line', a, b, arrow: 0|1|2, color, width}・{t: 'rect', x, y, w, h, color, width}・
  //     {t: 'ellipse', cx, cy, rx, ry, color, width}・{t: 'text', x, y, lines, color, size}
  //   戻す記録 undo：{k: 'add', obj}・{k: 'snap', obj, free}（形に直した。戻すと手書きに）・{k: 'edit', obj, prev}・{k: 'del', obj, index}・{k: 'clear', objs}
  //   書くのはマウスとペン（Apple Pencil）の入力だけ。指（touch）では書かない（手のひらで線が出ないように）
  //   start()・stop()・toggle()・active()、clear()：今のページの書き込みを全部消す、undo()：ひとつ戻す、cut()：書いている線をそこで切る、
  //   show()：今のページを描き直す、place()：舞台と同じ位置・縮小に置く、escape()：Esc の1段（窓を閉じる・ロックを外す。したら真）、
  //   count(key)：そのページ（既定は今）の数、hasAny()、drop(key)、paint(ctx, key)：舞台の座標の文脈にそのページを描く、state()
  function createWriting(opts) {
    let ink = null, tools = null, pop = null, ctx = null, on = false, shape = 'rect', locked = false, hl = false, cur = null, popKind = null;
    let removeBtn = null;                                          // 「この追加ページを消す」（追加ページにいるときだけ見せる）
    let sel = null, drag = null, editing = null, mini = null, miniKey = '';   // 選んでいるもの・引いている最中（動かす・つまみ）・文字の欄・小さな帯
    const pages = new Map();
    const keyNow = () => String(opts.pageKey());
    const pageOf = key => {
      if (!pages.has(key)) pages.set(key, { objs: [], undo: [] });
      return pages.get(key);
    };
    const kindOf = o => (o.t === 'line' ? (o.arrow ? 'arrow' : 'line') : o.t);
    // 種類ごとの今の色・太さ（保存された値を、値ごとに既定の上に重ねる）
    function styleOf(kind) {
      const saved = (opts.styles.get() || {})[kind] || {};
      return { ...WRITE_DEFAULTS[kind], ...saved };
    }
    // 描いた時の値をそのものに写す（あとで種類の設定を変えても、描いたものは変わらない）
    function styled(o) {
      const s = styleOf(kindOf(o));
      o.color = s.c;
      if (o.t === 'text') o.size = s.w; else o.width = s.w;
      if (o.t === 'free') o.r = s.r;
      return o;
    }
    function setStyle(kind, patch) {
      const s = { ...styleOf(kind), ...patch };
      opts.styles.set({ ...(opts.styles.get() || {}), [kind]: s });
    }

    function show() {
      if (!ctx) return;
      if (removeBtn) removeBtn.style.display = opts.isAdded() ? '' : 'none';
      ctx.clearRect(0, 0, STAGE_W, STAGE_H);
      const objs = pageOf(keyNow()).objs;
      if (sel && !objs.includes(sel)) sel = null;                 // 消えた（ひとつ戻す・別のページ）ものは選んだままにしない
      for (const o of objs) wPaintObject(ctx, o);
      if (cur) { const o = cur.box ? cur.preview : cur.free(); if (o) wPaintObject(ctx, o); }
      if (sel) paintSelection();
      syncMini();
    }
    function place() {
      if (!ink) return;
      const s = opts.stage.style;
      Object.assign(ink.style, { left: s.left, top: s.top, transformOrigin: '0 0', transform: s.transform, width: STAGE_W + 'px', height: STAGE_H + 'px' });
    }
    function toStage(e) {
      const r = ink.getBoundingClientRect();
      return [(e.clientX - r.left) * STAGE_W / r.width, (e.clientY - r.top) * STAGE_H / r.height];
    }
    const writes = e => e.pointerType === 'mouse' || e.pointerType === 'pen';
    const clone = o => JSON.parse(JSON.stringify(o));

    // ---- 選ぶ・動かす・大きさ・消す ----
    function bounds(o) {
      if (o.t === 'rect') return { x: o.x, y: o.y, w: o.w, h: o.h };
      if (o.t === 'ellipse') return { x: o.cx - o.rx, y: o.cy - o.ry, w: o.rx * 2, h: o.ry * 2 };
      if (o.t === 'line') return wBBox([o.a, o.b]);
      if (o.t === 'free') return wBBox(o.pts);
      ctx.save();
      ctx.font = `${o.size}px ${UI_FONT}`;
      const w = Math.max(...o.lines.map(l => ctx.measureText(l).width));
      ctx.restore();
      return { x: o.x, y: o.y, w, h: o.lines.length * o.size * WRITE_LINE_H };
    }
    function setBox(o, b) {
      if (o.t === 'rect') Object.assign(o, b);
      else Object.assign(o, { cx: b.x + b.w / 2, cy: b.y + b.h / 2, rx: b.w / 2, ry: b.h / 2 });
    }
    function hit(o, p) {
      if (o.t === 'line') {
        if (wSegDist(p, o.a, o.b) < o.width / 2 + 12) return true;
        return (o.arrow === 1 && wInTri(p, wArrowTri(o.b, o.a, o.width), 6)) || (o.arrow === 2 && wInTri(p, wArrowTri(o.a, o.b, o.width), 6));   // 頭の三角（短い矢印でも羽の角から選べる）
      }
      if (o.t === 'free') {
        if (o.pts.length === 1) return wDist(p, o.pts[0]) < 12;
        for (let i = 1; i < o.pts.length; i++) if (wSegDist(p, o.pts[i - 1], o.pts[i]) < o.width / 2 + 10) return true;
        return false;
      }
      const b = bounds(o), m = o.t === 'text' ? 8 : 12;
      return p[0] >= b.x - m && p[0] <= b.x + b.w + m && p[1] >= b.y - m && p[1] <= b.y + b.h + m;
    }
    const topAt = p => pageOf(keyNow()).objs.slice().reverse().find(o => hit(o, p)) || null;   // 後から描いた（上の）ものが先
    function handles() {
      if (!sel) return [];
      if (sel.t === 'line') return [{ at: sel.a, end: 'a' }, { at: sel.b, end: 'b' }];
      if (sel.t === 'rect' || sel.t === 'ellipse') {
        const b = bounds(sel), cs = [[b.x, b.y], [b.x + b.w, b.y], [b.x + b.w, b.y + b.h], [b.x, b.y + b.h]];
        return cs.map((q, i) => ({ at: q, anchor: cs[(i + 2) % 4] }));
      }
      return [];
    }
    const handleAt = p => handles().find(h => Math.abs(h.at[0] - p[0]) <= WRITE_HANDLE && Math.abs(h.at[1] - p[1]) <= WRITE_HANDLE) || null;
    function translate(o, dx, dy) {
      const mv = q => [q[0] + dx, q[1] + dy];
      if (o.t === 'free') o.pts = o.pts.map(mv);
      else if (o.t === 'line') { o.a = mv(o.a); o.b = mv(o.b); }
      else if (o.t === 'ellipse') { o.cx += dx; o.cy += dy; }
      else { o.x += dx; o.y += dy; }
    }
    function paintSelection() {
      const b = bounds(sel);
      ctx.save();
      ctx.strokeStyle = '#1b9bd1';
      ctx.lineWidth = 2;
      ctx.setLineDash([8, 6]);
      if (sel.t !== 'line') ctx.strokeRect(b.x - 8, b.y - 8, b.w + 16, b.h + 16);
      ctx.setLineDash([]);
      ctx.fillStyle = '#fff';
      ctx.lineWidth = 3;
      for (const h of handles()) { ctx.fillRect(h.at[0] - 9, h.at[1] - 9, 18, 18); ctx.strokeRect(h.at[0] - 9, h.at[1] - 9, 18, 18); }
      ctx.restore();
    }
    function select(o) {
      sel = o;
      show();
    }
    function removeSelected() {
      if (!sel) return;
      const page = pageOf(keyNow()), i = page.objs.indexOf(sel);
      if (i < 0) return;
      page.objs.splice(i, 1);
      page.undo.push({ k: 'del', obj: sel, index: i });
      sel = null;
      show();
    }
    // 選んだものの上（余地がなければ下）に出す小さな帯。矢印の向き（線だけ）・9色（蛍光ペンは除く）・消す
    function syncMini() {
      if (!mini) return;
      if (!sel || drag || !on) { mini.classList.remove('sp-on'); miniKey = ''; return; }
      const key = [sel.t, sel.arrow, sel.color, sel.hl].join('|');
      if (key !== miniKey) {
        miniKey = key;
        mini.textContent = '';
        const sep = () => mini.appendChild(el('i'));
        if (sel.t === 'line') {
          for (const [d, name] of [[0, 'ふつう'], [1, '終わりに矢印'], [2, '始めに矢印']]) {
            const b = el('button');
            b.type = 'button';
            b.dataset.arrow = String(d);
            b.title = b.ariaLabel = name;
            b.setAttribute('aria-pressed', String(sel.arrow === d));
            b.innerHTML = `<svg width="22" height="12" viewBox="0 0 22 12" aria-hidden="true"><line x1="${d === 2 ? 6 : 1}" y1="6" x2="${d === 1 ? 16 : 21}" y2="6" stroke="#fff" stroke-width="2"/>${d === 1 ? '<path d="M21 6 L14 1 L14 11 Z" fill="#fff"/>' : ''}${d === 2 ? '<path d="M1 6 L8 1 L8 11 Z" fill="#fff"/>' : ''}</svg>`;
            mini.appendChild(b);
          }
          sep();
        }
        if (!sel.hl) {
          for (const c of WRITE_COLORS) {
            const b = el('button', 'sp-write-dot');
            b.type = 'button';
            b.dataset.c = c;
            b.style.background = c;
            b.setAttribute('aria-label', c);
            b.setAttribute('aria-pressed', String(c === sel.color));
            mini.appendChild(b);
          }
          sep();
        }
        const del = el('button', '', '消す');
        del.type = 'button';
        del.dataset.del = '1';
        mini.appendChild(del);
      }
      mini.classList.add('sp-on');
      const r = ink.getBoundingClientRect(), k = r.width / STAGE_W, b = bounds(sel);
      let top = r.top + (b.y - 10) * k - mini.offsetHeight - 6;
      if (top < 0) top = r.top + (b.y + b.h + 10) * k + 6;
      const left = Math.max(0, Math.min(r.left + (b.x - 8) * k, window.innerWidth - mini.offsetWidth));
      Object.assign(mini.style, { left: left + 'px', top: top + 'px' });
    }

    // ---- 文字の欄 ----
    function openText(p) {
      if (editing) commitText();
      sel = null;
      show();
      const st = styleOf('text'), r = ink.getBoundingClientRect(), k = r.width / STAGE_W;
      const ta = el('textarea', 'sp-write-text');
      ta.rows = 1;
      ta.setAttribute('aria-label', '書き込みの文字');
      Object.assign(ta.style, { left: r.left + p[0] * k + 'px', top: r.top + p[1] * k + 'px', color: st.c, fontSize: st.w * k + 'px' });
      document.body.appendChild(ta);
      editing = { ta, p, color: st.c, size: st.w, key: keyNow() };
      const grow = () => {
        ta.style.height = 'auto';
        ta.style.height = ta.scrollHeight + 'px';
        ta.style.width = 'auto';
        ta.style.width = Math.max(120, ta.scrollWidth + 4) + 'px';
      };
      ta.addEventListener('input', grow);
      ta.addEventListener('keydown', ev => {
        if (ev.isComposing || ev.keyCode === 229) return;        // 変換中の Enter・Esc は変換に任せる
        if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); commitText(); }
        else if (ev.key === 'Escape') { ev.preventDefault(); cancelText(); }
      });
      ta.addEventListener('blur', () => setTimeout(() => { if (editing && editing.ta === ta) commitText(); }, 0));
      grow();
      ta.focus();
      requestAnimationFrame(() => { if (editing && editing.ta === ta) ta.focus(); });
    }
    function commitText() {
      if (!editing) return;
      const { ta, p, color, size, key } = editing;
      editing = null;
      const text = ta.value.replace(/\s+$/, '');
      ta.remove();
      if (text) add({ t: 'text', x: p[0], y: p[1], lines: text.split('\n'), color, size }, key);
      show();
    }
    function cancelText() {
      if (!editing) return;
      editing.ta.remove();
      editing = null;
    }

    function add(obj, key = keyNow()) {
      const page = pageOf(key);
      page.objs.push(obj);
      page.undo.push({ k: 'add', obj });
    }
    // ロック中：押した所から今の所までを □ か ○ の大きさにする（Shift で正方形・正円）
    function boxShape(a, p, square) {
      let w = p[0] - a[0], h = p[1] - a[1];
      if (square) { const m = Math.max(Math.abs(w), Math.abs(h)); w = Math.sign(w || 1) * m; h = Math.sign(h || 1) * m; }
      const x = Math.min(a[0], a[0] + w), y = Math.min(a[1], a[1] + h), W = Math.abs(w), H = Math.abs(h);
      return styled(shape === 'rect' ? { t: 'rect', x, y, w: W, h: H } : { t: 'ellipse', cx: x + W / 2, cy: y + H / 2, rx: W / 2, ry: H / 2 });
    }
    // 書いている途中の線を、手書きの1つにする
    function freeOf(pts) {
      const o = { t: 'free', pts: wResample(pts) };
      if (hl) return Object.assign(o, { color: WRITE_HL.color, width: WRITE_HL.width, r: 0, hl: true });
      return styled(o);
    }
    // 引いている最中の動かす・つまみを終える。変わったときだけ「変えた」を1つ記録する（引き始めたページに）。ページを移る・書き込みを終えるときにも使う
    function endDrag(cancelled) {
      if (!drag) return;
      const d = drag;
      drag = null;
      if (cancelled) { for (const k of Object.keys(sel)) delete sel[k]; Object.assign(sel, d.prev); }
      else if (JSON.stringify(sel) !== JSON.stringify(d.prev)) pageOf(d.key).undo.push({ k: 'edit', obj: sel, prev: d.prev });
    }
    function finish(e, cancelled) {
      if (drag && e.pointerId === drag.id) {
        endDrag(cancelled);
        show();
        return;
      }
      if (!cur || e.pointerId !== cur.id) return;
      const drawn = cur;
      cur = null;
      if (!cancelled) {
        if (drawn.box) {
          const o = drawn.preview;
          if (o && (o.t === 'rect' ? o.w : o.rx * 2) >= 8 && (o.t === 'rect' ? o.h : o.ry * 2) >= 8) add(o);
        } else if (wPathLen(drawn.pts) >= WRITE_CLICK) {          // 動かさずに押しただけ（ダブルクリックの手ぶれも）では何も描かない
          const free = freeOf(drawn.pts);
          const s = hl ? null : wRecognize(free.pts, shape);
          if (s) {
            const obj = styled(s), page = pageOf(keyNow());
            page.objs.push(obj);
            page.undo.push({ k: 'snap', obj, free });
          } else add(free);
        }
      }
      show();
    }

    function sampleSvg(kind) {
      const { c, w } = styleOf(kind), sw = w / 3;
      const body = {
        rect: `<rect x="4" y="4" width="26" height="16" fill="none" stroke="${c}" stroke-width="${sw}"/>`,
        ellipse: `<ellipse cx="17" cy="12" rx="13" ry="8" fill="none" stroke="${c}" stroke-width="${sw}"/>`,
        line: `<line x1="3" y1="12" x2="31" y2="12" stroke="${c}" stroke-width="${sw}" stroke-linecap="round"/>`,
        arrow: `<line x1="3" y1="12" x2="25" y2="12" stroke="${c}" stroke-width="${sw}" stroke-linecap="round"/><path d="M31 12 L23 7 L23 17 Z" fill="${c}"/>`,
        text: `<text x="17" y="17" text-anchor="middle" font-size="${w / 2.4}" fill="${c}">あ</text>`,
        free: `<path d="M3 15 C 9 3, 13 21, 19 10 S 27 6, 31 13" fill="none" stroke="${c}" stroke-width="${sw}" stroke-linecap="round"/>`,
      }[kind];
      return `<svg width="34" height="24" viewBox="0 0 34 24" style="background:#fff;border-radius:3px" aria-hidden="true">${body}</svg><span aria-hidden="true">▾</span>`;
    }
    function syncTools() {
      if (!tools) return;
      for (const b of tools.querySelectorAll('[data-shape]')) {
        const sel = b.dataset.shape === shape && !hl;
        b.setAttribute('aria-pressed', String(sel));
        b.classList.toggle('sp-lock', sel && locked);
      }
      tools.querySelector('[data-hl]').setAttribute('aria-pressed', String(hl));
      for (const b of tools.querySelectorAll('[data-kind]')) b.innerHTML = sampleSvg(b.dataset.kind);   // 色は決まった9色だけ（設定を読むときに確かめている）
    }
    function closePop() {
      if (pop) pop.classList.remove('sp-on');
      popKind = null;
    }
    function fillPop() {
      const kind = popKind, st = styleOf(kind);
      pop.textContent = '';
      const cols = el('div', 'sp-write-cols');
      for (const c of WRITE_COLORS) {
        const b = el('button');
        b.type = 'button';
        b.dataset.c = c;
        b.style.background = c;
        b.setAttribute('aria-label', c);
        b.setAttribute('aria-pressed', String(c === st.c));
        cols.appendChild(b);
      }
      pop.appendChild(cols);
      const row = (caption, list, attr, value) => {
        pop.appendChild(el('div', 'sp-write-cap', caption));
        const r = el('div', 'sp-write-opts');
        for (const [name, v] of list) {
          const b = el('button', '', name);
          b.type = 'button';
          b.dataset[attr] = String(v);
          b.setAttribute('aria-pressed', String(v === value));
          r.appendChild(b);
        }
        pop.appendChild(r);
      };
      if (kind === 'text') row('大きさ', WRITE_SIZES, 'w', st.w);
      else row('太さ', WRITE_WIDTHS, 'w', st.w);
      if (kind === 'free') row('描き味', WRITE_FEELS, 'r', st.r);
    }
    function openPop(kind, anchor) {
      if (pop.classList.contains('sp-on') && popKind === kind) { closePop(); return; }
      popKind = kind;
      fillPop();
      pop.classList.add('sp-on');
      const r = anchor.getBoundingClientRect();
      pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8)) + 'px';
      pop.style.top = r.bottom + 6 + 'px';
    }

    function build() {
      ink = el('canvas', 'sp-ink');
      ink.width = STAGE_W;
      ink.height = STAGE_H;
      ink.setAttribute('aria-hidden', 'true');
      document.body.appendChild(ink);
      ctx = ink.getContext('2d');
      ink.addEventListener('pointerdown', e => {
        if (!on || !writes(e) || e.button !== 0 || cur || drag) return;
        e.preventDefault();
        if (editing) commitText();                                // 欄の外を押すと決まる
        const p = toStage(e);
        if (sel) {
          const h = handleAt(p), grab = h ? { kind: 'handle', h } : hit(sel, p) ? { kind: 'move', last: p } : null;
          if (grab) {
            drag = { id: e.pointerId, key: keyNow(), prev: clone(sel), ...grab };
            try { ink.setPointerCapture(e.pointerId); } catch (err) { /* 捕まえられなくても、ink の上の動きで動かせる */ }
            return;
          }
          sel = null;                                             // ほかの所を押すと選ぶのをやめる
        }
        const boxed = locked && !hl;
        cur = { id: e.pointerId, key: keyNow(), pts: [p], box: boxed ? p : null, preview: null, free: () => freeOf(cur.pts) };
        try { ink.setPointerCapture(e.pointerId); } catch (err) { /* 捕まえられなくても、ink の上の動きで書ける */ }
        show();
      });
      ink.addEventListener('pointermove', e => {
        const q = toStage(e);
        if (drag && e.pointerId === drag.id) {
          if (drag.kind === 'move') { translate(sel, q[0] - drag.last[0], q[1] - drag.last[1]); drag.last = q; }
          else if (drag.h.end) sel[drag.h.end] = q;
          else {
            const a = drag.h.anchor;
            setBox(sel, { x: Math.min(a[0], q[0]), y: Math.min(a[1], q[1]), w: Math.max(24, Math.abs(q[0] - a[0])), h: Math.max(24, Math.abs(q[1] - a[1])) });
          }
          show();
          return;
        }
        if (!cur) { ink.style.cursor = sel ? (handleAt(q) ? 'nwse-resize' : hit(sel, q) ? 'move' : '') : ''; return; }
        if (e.pointerId !== cur.id) return;
        const evs = !cur.box && e.getCoalescedEvents ? e.getCoalescedEvents() : [];
        for (const ev of (evs.length ? evs : [e])) cur.pts.push(toStage(ev));
        if (cur.box) cur.preview = boxShape(cur.box, toStage(e), e.shiftKey);
        show();
      });
      ink.addEventListener('pointerup', e => finish(e, false));
      ink.addEventListener('pointercancel', e => finish(e, true));
      // ダブルクリックは選ぶだけ（マウスとペン）。矢印の向きは変えない
      ink.addEventListener('dblclick', e => {
        if (!on || (e.pointerType && !writes(e))) return;
        const o = topAt(toStage(e));
        if (o) select(o);
      });
      // 右クリックで文字（マウスだけ）。書き込みでないときは、ink が入力を受けないので、ブラウザーのメニューのまま
      ink.addEventListener('contextmenu', e => {
        if (!on) return;
        e.preventDefault();
        if (e.pointerType && e.pointerType !== 'mouse') return;
        openText(toStage(e));
      });
      // 窓の外を押すと閉じる（窓と、窓を開く見本の上は除く）
      document.addEventListener('pointerdown', e => {
        if (!pop.classList.contains('sp-on')) return;
        if (pop.contains(e.target) || (e.target.closest && e.target.closest('[data-kind]'))) return;
        closePop();
      }, true);

      tools = el('div', 'sp-write-tools');
      tools.setAttribute('role', 'toolbar');
      tools.setAttribute('aria-label', '書き込みの道具');
      const row1 = el('div', 'sp-write-row'), row2 = el('div', 'sp-write-row');
      const sample = kind => {
        const b = makeButton('', () => openPop(kind, b));
        b.classList.add('sp-write-sample');
        b.dataset.kind = kind;
        b.setAttribute('aria-label', { rect: '□ の色と太さ', ellipse: '○ の色と太さ', line: '線の色と太さ', arrow: '矢印の色と太さ', text: '文字の色と大きさ', free: '手書きの色と太さと描き味' }[kind]);
        return b;
      };
      const group = (...children) => { const g = el('span', 'sp-write-group'); for (const c of children) g.appendChild(c); return g; };
      for (const [kind, label] of [['rect', '□'], ['ellipse', '○']]) {
        // クリックで形を選び、ダブルクリックでロック。🔒 の幅はいつも空けてある（押している間に隣がずれて、ダブルクリックが外れないように）
        const b = makeButton(label, () => { shape = kind; locked = false; hl = false; syncTools(); });
        b.dataset.shape = kind;
        b.addEventListener('dblclick', () => { shape = kind; locked = true; hl = false; syncTools(); });
        row1.appendChild(group(b, sample(kind)));
      }
      for (const [kind, label] of [['line', '線'], ['arrow', '矢印'], ['text', '文字'], ['free', '手書き']]) {
        row1.appendChild(group(el('span', 'sp-write-label', label), sample(kind)));
      }
      const hlButton = makeButton('蛍光ペン', () => { hl = !hl; if (hl) locked = false; syncTools(); });
      hlButton.dataset.hl = '1';
      row1.appendChild(hlButton);
      row2.appendChild(makeButton('ひとつ戻す', () => undo()));
      row2.appendChild(makeButton('全部消す', () => clear()));
      row2.appendChild(el('i'));
      row2.appendChild(makeButton('白紙を足す', () => opts.onAddPage()));
      removeBtn = makeButton('この追加ページを消す', () => opts.onRemovePage());
      removeBtn.style.display = 'none';
      row2.appendChild(removeBtn);
      row2.appendChild(el('i'));
      row2.appendChild(makeButton('書き込みを終える（D）', () => stop()));   // 帯が隠れても、終える手段が残るように、書き込みの間は出したままにする
      tools.appendChild(row1);
      tools.appendChild(row2);
      document.body.appendChild(tools);

      mini = el('div', 'sp-write-mini');
      mini.addEventListener('click', e => {
        if (!sel) return;
        const a = e.target.closest('[data-arrow]'), c = e.target.closest('[data-c]'), d = e.target.closest('[data-del]');
        if (d) { removeSelected(); return; }
        if (!a && !c) return;
        const prev = clone(sel);
        if (a) { sel.arrow = Number(a.dataset.arrow); styled(sel); }      // 矢印にすると「矢印」の、ふつうに戻すと「線」の色と太さになる
        if (c) sel.color = c.dataset.c;
        pageOf(keyNow()).undo.push({ k: 'edit', obj: sel, prev });
        show();
      });
      document.body.appendChild(mini);

      pop = el('div', 'sp-write-pop');
      pop.addEventListener('click', e => {
        const b = e.target.closest('button');
        if (!b || !popKind) return;
        if (b.dataset.c) setStyle(popKind, { c: b.dataset.c });
        else if (b.dataset.w) setStyle(popKind, { w: Number(b.dataset.w) });
        else if (b.dataset.r) setStyle(popKind, { r: Number(b.dataset.r) });
        else return;
        fillPop();
        syncTools();
      });
      document.body.appendChild(pop);
      place();
    }
    function start() {
      if (on) return;
      if (!ink) build();
      on = true;
      ink.classList.add('sp-active');
      tools.classList.add('sp-on');
      syncTools();
      show();
      opts.onChange(true);
    }
    function stop() {
      if (!on) return;
      commitText();
      endDrag(false);
      sel = null;
      on = false;
      cur = null;
      locked = false;
      hl = false;
      closePop();
      ink.classList.remove('sp-active');
      tools.classList.remove('sp-on');
      syncTools();
      show();
      opts.onChange(false);
    }
    function clear() {
      const page = pageOf(keyNow());
      if (!page.objs.length) return;
      page.undo.push({ k: 'clear', objs: page.objs });
      page.objs = [];
      show();
    }
    function undo() {
      commitText();                                              // 入力中の文字は先に確定する（戻す対象になる。空の履歴と見なして追加ページを消さない）
      const page = pageOf(keyNow());
      const u = page.undo.pop();
      if (!u) { opts.onUndoEmpty(); return; }
      if (u.k === 'add') page.objs.splice(page.objs.indexOf(u.obj), 1);
      else if (u.k === 'snap') {
        page.objs[page.objs.indexOf(u.obj)] = u.free;
        page.undo.push({ k: 'add', obj: u.free });
      } else if (u.k === 'edit') {
        for (const key of Object.keys(u.obj)) delete u.obj[key];
        Object.assign(u.obj, u.prev);
      } else if (u.k === 'del') page.objs.splice(u.index, 0, u.obj);
      else if (u.k === 'clear') page.objs = u.objs;
      show();
    }
    function escStep() {
      if (!on) return false;
      if (editing) { cancelText(); return true; }
      if (sel) { select(null); return true; }
      if (pop && pop.classList.contains('sp-on')) { closePop(); return true; }
      if (locked) { locked = false; syncTools(); return true; }
      return false;
    }
    function state() {
      const kinds = {};
      for (const k of WRITE_KINDS) kinds[k] = styleOf(k);
      const page = pageOf(keyNow());
      return { active: on, page: keyNow(), count: page.objs.length, objects: page.objs.map(o => JSON.parse(JSON.stringify(o))), locked, shape, highlighter: hl, styles: kinds, selected: sel ? page.objs.indexOf(sel) : -1, editing: !!editing };
    }
    return {
      start, stop, clear, undo, show, place, state, escape: escStep,
      layout() {                                                 // 窓の大きさ・ノートなどが変わったあと：欄は決めて閉じ、層と小さな帯は置き直す
        commitText();
        place();
        show();
      },
      hasSelection: () => !!sel,
      removeSelected,
      toggle: () => (on ? stop() : start()),
      cut() {                                                    // 書いている途中の線は、始めたページに、そこまでを手書きとして残す（形にはしない）
        if (cur && !cur.box && wPathLen(cur.pts) >= WRITE_CLICK) add(cur.free(), cur.key);
        cur = null;
        commitText();
        endDrag(false);
        sel = null;
        show();
      },
      active: () => on,
      commitText,
      count: key => (pages.get(key == null ? keyNow() : String(key)) || { objs: [] }).objs.length,
      hasAny: () => Array.from(pages.values()).some(p => p.objs.length > 0),
      drop: key => { pages.delete(String(key)); show(); },
      paint: (c, key) => { for (const o of (pages.get(String(key)) || { objs: [] }).objs) wPaintObject(c, o); },
    };
  }

  function toggleFullscreen() {
    const root = document.documentElement;
    const full = document.fullscreenElement || document.webkitFullscreenElement;
    const fn = full ? (document.exitFullscreen || document.webkitExitFullscreen) : (root.requestFullscreen || root.webkitRequestFullscreen);
    if (typeof fn !== 'function') { toast(MSG_NO_FULLSCREEN); return; }
    try {
      const result = fn.call(full ? document : root);
      if (result && typeof result.catch === 'function') result.catch(() => toast(MSG_NO_FULLSCREEN));
    } catch (e) { toast(MSG_NO_FULLSCREEN); }
  }

  // ---- 直近の場所 ----

  // ページの場所：location.href から # 以降と ? 以降を除いたもの
  const pageKey = () => location.href.replace(/[?#].*$/, '');

  // 移り先にしてよいページの URL か（保存した中身で javascript: などへ移らないように）
  function isPageUrl(s) {
    if (typeof s !== 'string' || !s || /[?#]/.test(s)) return false;
    try { return LINK_PAGE_SCHEMES.includes(new URL(s).protocol); } catch (e) { return false; }
  }

  // 訪問の識別子：英小文字と数字の 12 文字の乱数（並びの中の識別子と重ならないもの）
  function newVid(taken) {
    const abc = 'abcdefghijklmnopqrstuvwxyz0123456789';
    for (;;) {
      const buf = new Uint8Array(12);
      try { crypto.getRandomValues(buf); } catch (e) { buf.forEach((_, i) => { buf[i] = Math.floor(Math.random() * 256); }); }
      const vid = Array.from(buf, b => abc[b % abc.length]).join('');
      if (!taken.some(p => p.vid === vid)) return vid;
    }
  }

  // 保存した並びを読む。形が違う（壊れた JSON、10件を超える、識別子・ページ・ID・段階（0〜10000 の整数）・位置の形が違う）ときは null
  function parsePlaces(text) {
    if (typeof text !== 'string') return null;
    let d;
    try { d = JSON.parse(text); } catch (e) { return null; }
    if (!d || typeof d !== 'object' || d.v !== 1 || !Array.isArray(d.items) || d.items.length > PLACES_MAX) return null;
    const items = [];
    for (const it of d.items) {
      if (!it || typeof it !== 'object') return null;
      const { vid, page, kind, ref, step, add } = it;
      if (typeof vid !== 'string' || !VID_RE.test(vid) || items.some(p => p.vid === vid)) return null;
      if (!isPageUrl(page) || (kind !== 'deck' && kind !== 'catalog')) return null;
      if (typeof ref !== 'string' || !REF_RE.test(ref) || !Number.isSafeInteger(step) || step < 0 || step > PLACE_STEP_MAX) return null;
      if (add !== undefined && (typeof add !== 'string' || !ADD_RE.test(add))) return null;   // 追加ページの識別子（あれば）
      items.push(add === undefined ? { vid, page, kind, ref, step } : { vid, page, kind, ref, step, add });
    }
    const pos = d.pos;
    if (!Number.isInteger(pos) || (items.length ? pos < 0 || pos >= items.length : pos !== -1)) return null;
    let restore = d.restore === undefined ? null : d.restore;
    if (restore !== null) {
      if (typeof restore !== 'object' || typeof restore.vid !== 'string' || !VID_RE.test(restore.vid) ||
          typeof restore.t !== 'number' || !Number.isFinite(restore.t)) return null;
      restore = { vid: restore.vid, t: restore.t };
    }
    return { items, pos, restore };
  }

  // 直近の場所の並びと今の位置。sessionStorage が使えないとき・書けなかったときは、このページの中（メモリー）だけで覚える
  const places = (() => {
    let items = [], pos = -1, restore = null;
    let readOk = false, writeOk = true;                          // 最後に読めたか・書けたか
    const copy = p => (p ? { ...p } : null);

    // 保存した並びを読み直す。壊れていれば捨てて空から始める。
    // 書けなかった後は、保存領域の中身が古いので読まず、メモリーの並びを使い続ける
    function load() {
      if (!writeOk) return;
      let text;
      try { text = window.sessionStorage.getItem(PLACES_KEY); readOk = true; } catch (e) { readOk = false; return; }
      const data = parsePlaces(text);
      if (data) ({ items, pos, restore } = data);
      else { items = []; pos = -1; restore = null; }
    }
    function save() {
      try {
        window.sessionStorage.setItem(PLACES_KEY, JSON.stringify({ v: 1, items, pos, restore }));
        writeOk = true;
      } catch (e) { writeOk = false; }
      return writeOk;
    }
    return {
      load, save,
      shared: () => readOk && writeOk,                           // ほかのページと並びを分け合えるか
      current: () => copy(items[pos]),
      find: vid => copy(items.find(p => p.vid === vid)),
      // 今の位置より先を捨てて末尾に足す。10件を超えたら一番古いものを捨てる
      visit(place) {
        items = items.slice(0, pos + 1);
        const p = { vid: newVid(items), page: place.page, kind: place.kind, ref: place.ref, step: place.step };
        if (place.add) p.add = place.add;
        items.push(p);
        if (items.length > PLACES_MAX) items = items.slice(items.length - PLACES_MAX);
        pos = items.length - 1;
        save();
        return copy(p);
      },
      // 今の場所の ID と段階（目次なら選んでいるデッキ）と追加ページを書き換える。並びと先の場所はそのまま
      updateCurrent(ref, step, add) {
        if (pos < 0) return;
        const next = { ...items[pos], ref, step };
        if (add) next.add = add; else delete next.add;
        items[pos] = next;
        save();
      },
      // 1か所前・先の場所（なければ null）。並びも今の位置も変えない（移るのは、select か復元先で）
      move: delta => (pos >= 0 ? copy(items[pos + delta]) : null),
      // 今の位置をその場所へ移す。並びは変えない
      select(vid) {
        const i = items.findIndex(p => p.vid === vid);
        if (i < 0) return null;
        if (i !== pos) { pos = i; save(); }
        return copy(items[i]);
      },
      // 別のページへの ←→ の前に、移る先の場所を時刻付きで保存する。保存できなければ false（何も残さない）
      setRestore(vid) {
        const before = restore;
        restore = { vid, t: Date.now() };
        if (save()) return true;
        restore = before;
        return false;
      },
      // 復元先を取り出して消す
      takeRestore() {
        const r = restore;
        if (r) { restore = null; save(); }
        return r;
      },
      clearRestore() {
        load();
        if (restore) { restore = null; save(); }
      },
      snapshot: () => ({ items: items.map(copy), pos }),
    };
  })();

  // ---- ブラウザの履歴項目の state（今いる場所の識別子を1つ書く）----

  function stateVid() {
    try {
      const s = history.state;
      return s && typeof s === 'object' && typeof s.spVid === 'string' ? s.spVid : null;
    } catch (e) { return null; }
  }

  // 今のページの見せ方。デッキ（startDeck）か目次が1つだけ登録する。着いたときの処理と ←→ が使う
  //   kind：場所の種類（"deck" | "catalog"）
  //   read(hash)：表示する所 {kind: "ok", ref, step} | {kind: "none"} | {kind: "bad"}
  //   resolve(ref, step, add)：保存した場所を、今のページで表示できる所にそろえる（ない ID なら null。追加ページがもうなければ元のスライドの最後の段階）
  //   first()：先頭。sameSlide(a, b, addA, addB)：同じスライドの同じページか（追加ページかどうか・どれかが違えば別。目次は同じページなら同じ）
  //   liveAdd(ref, add)：その追加ページがまだあればその識別子、なければ null（目次は常に null）
  //   show(ref, step, add)：並びを変えずに表示し、URL と state を書く
  //   msgBadHash：読めない hash のときに出す知らせ
  let view = null;

  const isOwn = p => !!p && p.page === pageKey() && p.kind === view.kind;
  const placeUrl = p => p.page + (p.kind === 'catalog' ? '#' + p.ref : formatHash(p.ref, p.step));

  // この文書が state に書こうとした識別子のうち、書けたと確かめられていないもの（replaceState が例外を投げた、または
  // 間引かれて state に残らなかった）。着いたときの処理が、state に識別子がないときの代わりに使う：
  // 書けなかった文書が、自分の今の場所を見失って、同じ場所を二重に足さないため（書けたと確かめられたら null に戻す）
  let unconfirmedVid = null;
  const arrivalVid = () => stateVid() || unconfirmedVid;

  // URL の hash と、今の履歴項目の state を書く。履歴は増やさず、変わったときだけ書く（約束 §3.4）。
  // state は {...history.state, spVid: 今の場所の識別子}。書いたあとで state を読み直し、残っているかを確かめる
  function writeLocation(hash) {
    const p = places.current();
    const vid = isOwn(p) ? p.vid : null;
    const hashChanged = location.hash !== hash;
    const stateChanged = vid !== null && stateVid() !== vid;
    if (hashChanged || stateChanged) {
      try {
        let st = history.state;
        if (stateChanged) st = { ...(st && typeof st === 'object' && !Array.isArray(st) ? st : {}), spVid: vid };
        if (hashChanged) history.replaceState(st, '', location.href.replace(/#.*$/, '') + hash);
        else history.replaceState(st, '');
      } catch (e) { /* 書けなくても、表示とページの中の移動は続ける（約束 §3.2） */ }
    }
    if (vid !== null) unconfirmedVid = stateVid() === vid ? null : vid;
  }

  // 規定の順序や Shift などで動いたとき：別のスライドなら新しい場所を足し、同じスライドで段階だけなら今の場所を書き換える。
  // ID が約束の形でないスライドは記録しない（保存した並びは ID の形が違うと全体が壊れたものとして捨てられるので、並び全体を守る）
  function record(ref, step, add = null) {
    if (!isRef(ref)) return;
    const p = places.current();
    if (isOwn(p) && view.sameSlide(p.ref, ref, p.add || null, add)) {
      if (p.ref !== ref || p.step !== step || (p.add || null) !== add) places.updateCurrent(ref, step, add);
    } else {
      places.visit({ page: pageKey(), kind: view.kind, ref, step, add });
    }
  }

  // ---- ページに着いたときの処理 ----
  // 初めての読み込み・再読み込み・ブラウザの戻る・進む・ページキャッシュからの復帰（pageshow）、
  // 同じページの中の戻る・進む（popstate）、アドレス欄の hash の変更（hashchange）のすべてで、この1つを通す。
  // 毎回、その時点の URL・history.state・保存した並び（読み直す）から決める。「処理済みだから飛ばす」はしない。
  // 同じ遷移で popstate と hashchange が続いても、2回目は1回目が書いた識別子に合うので「同じ」になり、二重に足さない
  const liveAdd = (ref, add) => (add && view.liveAdd ? view.liveAdd(ref, add) : null);
  function arrive() {
    if (!view) return;
    places.load();
    const restore = places.takeRestore();                        // 使えても使えなくても消す

    // 2. 並びのどこに合わせるか：復元先（10秒以内・並びの中・このページの場所）、次に state の識別子
    let matched = null;
    if (restore) {
      const age = Date.now() - restore.t;
      const p = places.find(restore.vid);
      if (age >= 0 && age <= RESTORE_MS && isOwn(p)) matched = p;
    }
    if (!matched) {
      const p = places.find(arrivalVid());                       // state の識別子。なければ、この文書が書けなかった識別子
      if (isOwn(p)) matched = p;
    }
    if (matched) places.select(matched.vid);

    // 1. 表示する所：読める hash のとおり。hash がなければ合わせた場所、それもなければ先頭。読めない hash は先頭
    const shown = view.read(location.hash);
    let target = shown.kind === 'ok' ? shown : null;
    const matchedAdd = matched ? liveAdd(matched.ref, matched.add) : null;     // 合わせた場所の追加ページ（もうなければ null＝元のスライド）
    if (target && matchedAdd && target.ref === matched.ref && target.step === matched.step) target = { ...target, add: matchedAdd };   // hash は元のスライド：追加ページがまだあれば、それを出す
    if (!target && shown.kind === 'none' && matched) target = view.resolve(matched.ref, matched.step, matched.add);
    if (!target) target = view.first();
    const targetAdd = target.add || null;

    // 3. 合わせた場所と比べる：なし・違うスライドなら足す。段階（目次なら選ぶデッキ）だけ違えば書き換える。同じなら何もしない。
    //    ID が約束の形でないスライドは記録しない（record と同じ）
    if (!isRef(target.ref)) {
      /* 記録しない */
    } else if (!matched || !view.sameSlide(matched.ref, target.ref, matchedAdd, targetAdd)) {
      places.visit({ page: pageKey(), kind: view.kind, ref: target.ref, step: target.step, add: targetAdd });
    } else if (matched.ref !== target.ref || matched.step !== target.step || (matched.add || null) !== targetAdd) {
      places.updateCurrent(target.ref, target.step, targetAdd);
    }

    // 4. 表示し、URL と state（今いる場所の識別子）を書く
    view.show(target.ref, target.step, targetAdd);
    if (shown.kind === 'bad') toast(view.msgBadHash);
  }

  function listenArrivals() {
    window.addEventListener('pageshow', arrive);
    window.addEventListener('popstate', arrive);
    window.addEventListener('hashchange', arrive);
  }

  // 直近の場所へ移る（←→ と、縮小一覧の「直近の場所」の列で共通）。並びは変えない。移れたら true
  //   同じページ：今の位置をその場所に合わせて表示する。
  //   別のページ：移る先を復元先として保存してから、その場所の URL へ移る。
  //   保存領域が使えない・書けないときは移れない（refuseMessage を知らせて、そのまま）
  function goToPlace(target, refuseMessage) {
    if (isOwn(target)) {
      places.select(target.vid);
      view.show(target.ref, target.step, target.add || null);
      return true;
    }
    if (!places.shared() || !places.setRestore(target.vid)) { toast(refuseMessage); return false; }
    markArrival();
    location.href = placeUrl(target);
    return true;
  }

  // ←・→：直近の場所を1か所前・先へ。並びは変えない。
  //   ← で先頭のときは、動かず知らせる。→ で先の場所がないときは、知らせずに orElse（今の画面の ↓ の動き）をする。
  //   先の場所はあるが別のページへ移れないときは、どちらの向きも動かず知らせる
  function movePlace(delta, orElse) {
    const edgeMessage = delta < 0 ? MSG_PLACE_FIRST : MSG_PLACE_LAST;
    const target = places.move(delta);
    if (!target) {
      if (delta > 0 && orElse) orElse();
      else toast(edgeMessage);
      return;
    }
    goToPlace(target, edgeMessage);
  }

  // 別のページの場所のページ名：URL のファイル名から拡張子を除いたもの。ファイル名が slides・index のときは、1つ上のフォルダー名
  // （.../ch-02/slides.html → ch-02。上のフォルダーがなければファイル名のまま）。
  // 取り出すのは末尾のファイル名・フォルダー名だけで、それぞれ復号する。復号できなければその生の文字列を使う。
  // どれも取り出せなければ「別ページ」。どの場合も、元の URL 全体（手元のフルパスなど）は返さない
  function pageName(url) {
    const decode = text => { try { return decodeURIComponent(text); } catch (e) { return text; } };
    let names;
    try { names = new URL(url).pathname.split('/').filter(Boolean); } catch (e) { return PAGE_NAME_FALLBACK; }
    const file = decode(names[names.length - 1] || '');
    const stem = file.replace(/\.[^./]*$/, '') || file;
    if ((stem === 'slides' || stem === 'index') && names.length > 1) return decode(names[names.length - 2]) || PAGE_NAME_FALLBACK;
    return stem || PAGE_NAME_FALLBACK;
  }

  // 別のページの場所の短い呼び名：「ページ名：ID」（段階が1以上なら「・段階N」。ID がなければページ名だけ）。
  // 縮小一覧の直近の場所の列と、リンクを表示の札（別のページへの jump）の両方がこれを使う
  function placeLabel(url, ref, step) {
    const name = pageName(url);
    if (!ref) return name;
    return `${name}：${ref}` + (step > 0 ? `・段階${step}` : '');
  }

  // リンクの行き先の URL（解決済み）の短い呼び名。hash が「ID」か「ID.段階」の形のときだけ ID を付ける
  function urlLabel(url) {
    let ref = '', step = 0;
    try {
      const m = LINK_ID_RE.exec(decodeURIComponent(url.hash.replace(/^#/, '')));
      if (m) { ref = m[1]; step = m[2] === undefined ? 0 : parseInt(m[2], 10); }
    } catch (e) { /* 壊れたパーセント表記は、ページ名だけ */ }
    return placeLabel(url.href, ref, step);
  }

  // リンク・H・目次から開くなど、←→ 以外でページを移るときはここを通す（残っている復元先を消してから移る）
  function openPage(url) {
    places.clearRestore();
    markArrival();
    location.href = url;
  }

  // ---- 切り替えの動きの共通の道具 ----

  // OS の「視差効果を減らす」が入っているか（移動のたびに確かめる。確かめられなければ入っていない扱い）
  function prefersReducedMotion() {
    try { return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); } catch (e) { return false; }
  }
  // 動かしてよいか：設定が「あり」で、OS が止めていない
  const motionAllowed = () => settings.get().motion && !prefersReducedMotion();
  // WebKit か（iPhone・iPad ではどのブラウザもこれになる）。舞台だけに名前を付けると入ってくる側が写らないので、ページ全体を動かす
  const isWebKit = () => navigator.vendor === 'Apple Computer, Inc.';

  // 別のページへ移る前に、時刻を書く。着いた側は10秒以内なら、フェードインで現れる（読めない・書けないときは動かさないだけ）
  function markArrival() {
    if (!motionAllowed() || !Element.prototype.animate) return;
    try { window.sessionStorage.setItem(ARRIVE_KEY, String(Date.now())); } catch (e) { /* 書けなければ動かさない */ }
  }
  // 着いた側：書かれた時刻を読み、必ず消す。10秒以内なら true
  function takeArrival() {
    let text = null;
    try {
      text = window.sessionStorage.getItem(ARRIVE_KEY);
      window.sessionStorage.removeItem(ARRIVE_KEY);
    } catch (e) { return false; }
    if (typeof text !== 'string' || !/^\d+$/.test(text)) return false;
    const age = Date.now() - Number(text);
    return age >= 0 && age <= ARRIVE_WINDOW_MS;
  }
  // 着いた側で node をフェードインさせる。結果：{played, done}（done は終わると解決する Promise）。
  // allowed：着いた側が送りを許しているか（デッキが「送りなし」を選んだら false）。許さないときも、印は使って消す
  function playArrival(node, allowed = true) {
    const none = { played: false, done: Promise.resolve() };
    if (!takeArrival() || !allowed || !motionAllowed() || !node.animate) return none;
    try {
      const a = node.animate([{ opacity: 0 }, { opacity: 1 }], { duration: MOTION_ARRIVE_MS, easing: 'ease' });
      return { played: true, done: a.finished.then(() => {}, () => {}) };
    } catch (e) { return none; }
  }

  // ---- 組み立て ----

  function start() {
    if (window.slideDeck) startDeck();
    else if (window.slideCatalog) startCatalog();
    // どちらもないページでは何もしない
  }

  // プレイヤーの CSS を入れる（デッキと目次で共通。html・body の余白とスクロールを抑える指定も含む）。2回目からは何もしない
  function installStyle() {
    if (document.querySelector('style.sp-style')) return;
    const style = document.createElement('style');
    style.className = 'sp-style';
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  // ---- 目次のページ（約束 §4）----

  // 1ページのカードの数：幅 1200px 以上で3、760px 以上で2、それより狭いと1
  const cardsPerPage = () => (window.innerWidth >= CATALOG_WIDE_PX ? 3 : window.innerWidth >= CATALOG_MID_PX ? 2 : 1);

  // slideCatalog.decks を、描ける形にそろえる。オブジェクトでないものは捨てる。
  // カードの ID は場所の記録と hash に使うので、形が正しく（REF_RE）一意なものだけを使い、なければ "card-N" を付ける。
  // 色は CSS の色として読めるものだけ使う。kind が "page" でないものはデッキとして扱う
  function catalogCards(list) {
    const text = v => (typeof v === 'string' ? v : '');
    const cards = [], seen = new Set();
    for (const d of Array.isArray(list) ? list : []) {
      if (!d || typeof d !== 'object') continue;
      let id = typeof d.id === 'string' && REF_RE.test(d.id) && !seen.has(d.id) ? d.id : null;
      for (let n = cards.length + 1; id === null; n++) if (!seen.has('card-' + n)) id = 'card-' + n;
      seen.add(id);
      let color = '';
      try { if (typeof d.color === 'string' && window.CSS.supports('color', d.color)) color = d.color; } catch (e) { /* 色が使えなければ既定 */ }
      cards.push({
        id, color, page: d.kind === 'page',
        href: text(d.href), label: text(d.label), title: text(d.title) || id, meta: text(d.meta),
        items: Array.isArray(d.items) ? d.items.filter(x => typeof x === 'string' && x !== '') : [],
      });
    }
    return cards;
  }

  // カードを開く URL（カードの href を、この目次のページからの相対 URL として読む）。hash は足さない
  // （デッキは先頭のスライドに着く）。開いてよい種類（file・http・https）でなければ null
  function cardUrl(card) {
    if (!card.href) return null;
    try {
      const u = new URL(card.href, location.href);
      return LINK_PAGE_SCHEMES.includes(u.protocol) ? u : null;
    } catch (e) { return null; }
  }

  function startCatalog() {
    const catalog = window.slideCatalog;
    settings.load();                                             // 切り替えの動きの設定を読む（着いたときのフェードイン）
    let arrival = { played: false, done: Promise.resolve() };    // 着いたときのフェードイン（playArrival の結果）
    const cards = catalogCards(catalog.decks);
    if (!cards.length) {
      console.warn('プレイヤー：目次（slideCatalog.decks）にカードがないので、何もしません');
      return;
    }
    installStyle();                                              // html・body の余白とスクロールを抑える指定も、ここで入る
    const indexOfId = id => cards.findIndex(c => c.id === id);

    // ---- 画面 ----
    const root = el('div', 'sp-catalog');
    root.setAttribute('aria-label', '目次');
    const head = el('div', 'sp-catalog-head');
    const title = el('div', 'sp-catalog-title', typeof catalog.title === 'string' ? catalog.title : '');
    title.setAttribute('role', 'heading');
    title.setAttribute('aria-level', '1');
    head.appendChild(title);
    if (typeof catalog.lead === 'string' && catalog.lead) head.appendChild(el('div', 'sp-catalog-lead', catalog.lead));
    const grid = el('div', 'sp-cards');
    grid.setAttribute('role', 'group');
    grid.setAttribute('aria-label', 'カード');
    const pager = el('div', 'sp-pager');
    pager.setAttribute('role', 'group');
    pager.setAttribute('aria-label', 'ページの切り替え');

    let sel = 0, pageNo = 0, perPage = cardsPerPage();           // 選んでいるカード・見せているページ・1ページのカードの数
    let lastX = -1, lastY = -1;                                  // マウスの最後の位置（動いたときだけ選ぶため）
    const nodes = cards.map((card, i) => {
      const node = el('div', 'sp-card');
      node.dataset.id = card.id;
      node.dataset.kind = card.page ? 'page' : 'deck';
      node.setAttribute('role', 'link');
      node.tabIndex = -1;                                        // 焦点が乗るのは選んでいる1枚だけ（setSelection が付け替える）
      if (card.color) node.style.setProperty('--c', card.color);
      if (!card.page && card.label) node.appendChild(el('div', 'sp-card-label', card.label));      // page はデッキの情報（節の呼び名）を持たない
      node.appendChild(el('div', 'sp-card-title', card.title));
      // items・meta は、デッキも page も、あれば出す（汎用の講座のチートシートの「A4 1枚」など）。どちらもない page は題だけを中央に出す
      if (card.items.length) {
        const list = el('ul', 'sp-card-items');
        for (const item of card.items) list.appendChild(el('li', 'sp-card-item', item));
        node.appendChild(list);
      }
      if (card.meta) node.appendChild(el('div', 'sp-card-meta', card.meta));
      node.classList.toggle('sp-card-bare', card.page && !card.items.length && !card.meta);
      // 止まっているマウスの下にカードが入れ替わっても選ばない（動いたときだけ選ぶ）。押すと開く
      node.addEventListener('mousemove', e => {
        if (e.clientX === lastX && e.clientY === lastY) return;
        lastX = e.clientX;
        lastY = e.clientY;
        choose(i, false);
      });
      node.addEventListener('click', () => openCard(i));
      grid.appendChild(node);
      return node;
    });
    root.append(head, grid, pager, el('div', 'sp-catalog-hint', CATALOG_KEYS_HINT));
    document.body.appendChild(root);

    const pageCount = () => Math.ceil(cards.length / perPage);

    // ページの切り替えのボタン（1ページなら出さない）。1ページのカードの数が変わったときに作り直す
    function buildPager() {
      pager.textContent = '';
      pager.hidden = pageCount() <= 1;
      for (let p = 0; pageCount() > 1 && p < pageCount(); p++) {
        const first = p * perPage, last = Math.min(first + perPage, cards.length);
        const b = makeButton(last - first > 1 ? `${first + 1}〜${last}` : `${first + 1}`, () => { if (p !== pageNo) choose(first, false); });
        b.classList.add('sp-pager-btn');
        pager.appendChild(b);
      }
    }

    // 選んでいるカードのあるページを見せる（ほかのページのカードは hidden）
    function showPage() {
      pageNo = Math.floor(sel / perPage);
      nodes.forEach((n, i) => { n.hidden = Math.floor(i / perPage) !== pageNo; });
      pager.querySelectorAll('.sp-pager-btn').forEach((b, p) => {
        if (p === pageNo) b.setAttribute('aria-current', 'page');
        else b.removeAttribute('aria-current');
      });
    }

    // 選びを i にする（表示だけ。場所の記録と hash は choose と view.show がする）。
    // 焦点が（ページの切り替えの前に）カードの中にあったとき・focus のときは、選んだカードへ焦点を移す
    function setSelection(i, focus) {
      const hadFocus = grid.contains(document.activeElement);
      sel = i;
      nodes.forEach((n, k) => {
        n.classList.toggle('sp-selected', k === i);
        n.tabIndex = k === i ? 0 : -1;
        if (k === i) n.setAttribute('aria-current', 'true');
        else n.removeAttribute('aria-current');
      });
      showPage();
      if (focus || hadFocus) nodes[i].focus({ preventScroll: true });
    }

    // 利用者の操作でカード i を選ぶ。選びだけが変わるので、今の場所の ref を書き換える（場所は増やさない）。hash も書き換える
    function choose(i, focus) {
      if (i === sel) return;
      setSelection(i, focus);
      record(cards[i].id, 0);
      writeLocation('#' + cards[i].id);
    }

    function moveSelection(delta) {
      const next = sel + delta;
      if (next < 0) toast(MSG_CARD_FIRST);
      else if (next >= cards.length) toast(MSG_CARD_LAST);
      else choose(next, true);
    }

    // 前後のページの最初のカード
    function movePage(delta) {
      const target = pageNo + delta;
      if (target < 0) toast(MSG_PAGE_FIRST);
      else if (target >= pageCount()) toast(MSG_PAGE_LAST);
      else choose(target * perPage, true);
    }

    // カードを開く。先に選んでから開く（← で戻ったとき、開いたカードが選ばれているように）。
    // 別のページへは openPage を通る（残っている復元先を消してから移る）。行き先が使えなければ知らせて、何もしない
    function openCard(i) {
      if (i < 0 || i >= cards.length) return;
      choose(i, false);
      const url = cardUrl(cards[i]);
      if (!url) { toast(MSG_CARD_BLOCKED); return; }
      openPage(url.href);
    }

    // ページに着いたときの処理（arrive）と ←→ に、この目次の見せ方を渡す
    view = {
      kind: 'catalog',
      msgBadHash: MSG_CATALOG_BAD_HASH,
      read(hash) {
        hash = String(hash);
        if (hash === '' || hash === '#') return { kind: 'none' };
        let id;
        try { id = decodeURIComponent(hash.slice(1)); } catch (e) { return { kind: 'bad' }; }
        return hash[0] === '#' && indexOfId(id) >= 0 ? { kind: 'ok', ref: id, step: 0 } : { kind: 'bad' };
      },
      resolve: ref => (indexOfId(ref) >= 0 ? { ref, step: 0 } : null),
      first: () => ({ ref: cards[0].id, step: 0 }),
      sameSlide: () => true,                                     // 目次は同じページなら同じ場所（選んでいるカードが違うだけ）
      show(ref) {
        let i = indexOfId(ref);
        if (i < 0) { i = 0; toast(MSG_CATALOG_GONE); }
        setSelection(i, false);
        writeLocation('#' + cards[i].id);
      },
    };

    // ---- 操作の一覧（?）：デッキと同じ共通の重なり。目次で使えるキーの一覧 ----
    const help = createHelp({ rows: CATALOG_HELP_KEYS });

    // ---- キー操作（目次）----
    // ↑↓ 順に選ぶ、Shift＋↑↓ 前後のページ、Enter 開く、1〜9 N番目を開く、←→ 直近の場所（デッキと同じ movePlace。先の場所がないときの → は ↓ と同じ）、? 操作の一覧、Esc 閉じる

    // キーに対する動き（なければ null）。指で払う操作も、これを呼ぶ
    function actionFor(e) {
      switch (e.key) {
        case 'ArrowDown': return () => (e.shiftKey ? movePage(1) : moveSelection(1));
        case 'ArrowUp': return () => (e.shiftKey ? movePage(-1) : moveSelection(-1));
        case 'ArrowLeft': return e.shiftKey ? null : () => movePlace(-1);
        case 'ArrowRight': return e.shiftKey ? null : () => movePlace(1, () => moveSelection(1));
        case 'Enter': return () => { if (!e.repeat) openCard(sel); };
        default: return !e.shiftKey && /^[1-9]$/.test(e.key) && Number(e.key) <= cards.length ? () => { if (!e.repeat) openCard(Number(e.key) - 1); } : null;
      }
    }

    document.addEventListener('keydown', e => {
      if (e.defaultPrevented || ignoredKey(e)) return;
      if (isOwnButton(e.target) && (e.key === ' ' || e.key === 'Enter')) return;      // 焦点が乗ったボタンの Space・Enter は、そのボタンを押す動作
      const top = overlays.top();
      if (e.key === '?') { e.preventDefault(); if (!e.repeat) help.toggle(); return; }
      if (e.key === 'Escape') { if (top) { e.preventDefault(); top.close(); } return; }
      if (top && top.modal) {                                    // 重なりが開いている間は、選びも移動も動かさない。Tab は重なりの中だけを巡る
        if (e.key === 'Tab') { e.preventDefault(); overlays.trapTab(top, e); }
        return;
      }
      const action = actionFor(e);
      if (!action) return;
      e.preventDefault();
      action();
    });

    // 指で払う操作：キーと同じ動き（actionFor）を、払った向きの矢印キーとして呼ぶ（Shift なし）
    createSwipe({ onSwipe: dir => { const action = actionFor({ key: SWIPE_KEYS[dir], shiftKey: false }); if (action) action(); } });

    // 幅が変わって1ページのカードの数が変わったら、選んでいるカードを含むページに作り直す
    window.addEventListener('resize', () => {
      const n = cardsPerPage();
      if (n === perPage) return;
      perPage = n;
      grid.style.setProperty('--n', String(n));
      buildPager();
      showPage();
    });
    listenArrivals();

    // 試験用の窓口（通常の表示のときだけ）。index は選んでいるカードの番号（0 から）、id はそのカードの ID
    window.__sp = {
      state: () => ({ kind: 'catalog', index: sel, step: 0, id: cards[sel].id }),
      places: () => places.snapshot(),
      overlay: () => overlays.name(),
      motion: () => ({ kind: 'none', arrival: arrival.played }),
      motionDone: () => arrival.done,
      parseHash, formatHash, openPage,
    };

    grid.style.setProperty('--n', String(perPage));
    buildPager();
    arrive();
    arrival = playArrival(grid);                                 // 別のページから移ってきたときだけ、カードの並び全体をフェードインさせる
  }

  // ---- メモの保存の部品 ----
  // 欄1つを1つの localStorage のキーに保存する：デッキ全体を1つの値にすると、2つのタブが同時に書いたときに片方が消えるため。
  //   get(slideId, field)：文字列（なければ ''）。待っている分・書けなかった分（ページの中の写し）が先。壊れた値（長すぎる・文字列でない）は '' として扱う
  //   set(slideId, field, text)：ページの中の写しをすぐ変え、500ms 待って、待っている欄のキーだけを書く（空ならキーを消す）
  //   flush()：待っている分をすぐ書く。all(field)：このページの接頭辞のキーを集めた Map<slideId, 文字列>（空は入れない）
  //   onSaved(fn)：flush でキーを書けた・消せたとき fn(slideId, field, text) を呼ぶ（書けなかったときは呼ばない）
  //   onChange(fn)：ほかのタブが書いたとき fn(slideId, field) を呼ぶ（slideId が null なら全部）。failed()：書けなかったことがあるか。onFail(fn)：最初に書けなかったとき1回呼ぶ
  // 読み書きはすべて try/catch で囲み、使えなくてもこのページの中の値で動く
  function createMemoStore(page) {
    const prefix = `${MEMO_KEY_PREFIX} ${page} `;
    const keyOf = (slideId, field) => `${prefix}${slideId} ${field}`;
    const pending = new Map();                                   // まだ書いていない値（キー → 文字列）
    const kept = new Map();                                      // 書けなかった値（ページの中だけで覚える）
    const listeners = [], savedListeners = [];
    let timer = 0, failed = false, failFn = null;
    const valid = v => typeof v === 'string' && v.length <= MEMO_MAX_CHARS;
    function read(key) {
      try { const v = window.localStorage.getItem(key); return valid(v) ? v : ''; } catch (e) { return ''; }
    }
    function fail() {
      if (failed) return;
      failed = true;
      if (failFn) failFn();
    }
    function flush() {
      clearTimeout(timer);
      timer = 0;
      for (const [key, text] of pending) {
        try {
          if (text === '') window.localStorage.removeItem(key); else window.localStorage.setItem(key, text);
          kept.delete(key);
          const rest = key.slice(prefix.length), cut = rest.lastIndexOf(' ');
          for (const fn of savedListeners) fn(rest.slice(0, cut), rest.slice(cut + 1), text);
        } catch (e) {
          kept.set(key, text);
          fail();
        }
      }
      pending.clear();
    }
    function get(slideId, field) {
      const key = keyOf(slideId, field);
      if (pending.has(key)) return pending.get(key);
      if (kept.has(key)) return kept.get(key);
      return read(key);
    }
    function set(slideId, field, text) {
      text = String(text).slice(0, MEMO_MAX_CHARS);
      if (text === get(slideId, field)) return;
      pending.set(keyOf(slideId, field), text);
      clearTimeout(timer);
      timer = setTimeout(flush, MEMO_SAVE_MS);
    }
    function all(field) {
      const out = new Map(), suffix = ` ${field}`;
      const take = (key, text) => {
        if (!key.startsWith(prefix) || !key.endsWith(suffix) || key.length <= prefix.length + suffix.length) return;
        const id = key.slice(prefix.length, key.length - suffix.length);
        if (text === '') out.delete(id); else out.set(id, text);
      };
      try {
        for (let i = 0; i < window.localStorage.length; i++) {
          const key = window.localStorage.key(i);
          if (key && key.startsWith(prefix)) take(key, read(key));
        }
      } catch (e) { /* 数えられなければ、ページの中の写しだけ */ }
      for (const [key, text] of kept) take(key, text);
      for (const [key, text] of pending) take(key, text);        // ページの中の写しの方が新しい
      return out;
    }
    window.addEventListener('storage', e => {
      if (e.storageArea && e.storageArea !== window.localStorage) return;
      if (e.key === null) { for (const fn of listeners) fn(null, null); return; }
      if (!e.key.startsWith(prefix)) return;
      const rest = e.key.slice(prefix.length), cut = rest.lastIndexOf(' ');
      if (cut < 1 || pending.has(e.key)) return;                 // ここで書いている途中の欄は、こちらの値が新しい
      kept.delete(e.key);
      for (const fn of listeners) fn(rest.slice(0, cut), rest.slice(cut + 1));
    });
    window.addEventListener('pagehide', flush);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flush(); });
    return { get, set, flush, all, failed: () => failed, onChange: fn => { listeners.push(fn); }, onSaved: fn => { savedListeners.push(fn); }, onFail: fn => { failFn = fn; } };
  }

  function startDeck() {
    const rawSlides = window.slideDeck.info && window.slideDeck.info.slides;
    const stage = document.getElementById('stage');
    if (!Array.isArray(rawSlides) || !rawSlides.length || !stage) {
      console.warn('プレイヤー：デッキ（slideDeck.info.slides）か舞台（#stage）がないので、何もしません');
      return;
    }
    const slides = normalizeSlides(rawSlides);                   // steps をそろえた写し（中身のデータは書き換えない）
    const deckMotion = normalizeDeckMotion(window.slideDeck.info.motion);   // デッキが選んだ動きの層
    // 効くのは「デッキが選んだもの」かつ「見る人が止めていないもの」
    const sendAllowed = () => deckMotion.send && motionAllowed();
    const entryStyle = () => (motionAllowed() ? deckMotion.entry : null);
    const pointOn = () => deckMotion.point;
    const canHover = () => { try { return window.matchMedia('(hover: hover) and (pointer: fine)').matches; } catch (e) { return false; } };
    const modalOpen = () => { const top = overlays.top(); return !!(top && top.modal); };
    const lightOn = () => pointOn() && settings.get().light && canHover() && !modalOpen() && !(writing && writing.active()) && !curAdd;

    installStyle();
    installPrintStyle();
    stage.classList.add('sp-target');                            // どの描画先にも sp-target を付ける（約束 §2.5）

    let cur = 0, curStep = 0;                                    // 今のスライドの位置（0 から）と段階
    let curAdd = null;                                           // 今いる追加ページの識別子（ふつうのスライドなら null）。追加ページにいる間の cur・curStep は元のスライドの最後の段階
    // 追加ページ（保存しない。このページを開いている間だけ）：元のスライドの番号 → 識別子の並び（表示の順）。識別子は 'x' + 連番（増えるだけ）。
    // 連番の始まりは読み込みごとに変える（保存した直近の場所に残った古い識別子が、読み直したあとに足した別の追加ページに合わないように）
    const adds = new Map();
    let addCounter = Math.floor(Math.random() * 800000) + 1;
    const addsOf = i => adds.get(i) || [];
    const stageAt = { index: -1, step: -1 };                     // 舞台に今描いてあるスライドと段階
    let overviewEl = null;                                       // 縮小一覧の要素（開いていなければ null）。go が見るので、ここで宣言する
    let linkViewEl = null, moreEl = null;                        // リンクを表示・補足の窓の要素（開いていなければ null）。go と fitStage が見るので、ここで宣言する
    let linkFrames = [];                                         // リンクを表示の枠：{frame, tag, node}
    let linkPanelEl = null;                                      // リンクを表示の隅の一覧（閉じるボタンと、場所のないリンク）
    let markLayer = null;                                        // リンクの印の文字を重ねる層（舞台の外。最初に印を置くときに作る）
    let stageScale = 1;                                          // 舞台の縮小の倍率（fitStage が決める）
    let sideEl = null, sideItems = [], sideAddItems = [], sideMarked = null;          // 一覧つきの画面の左の列・そのスライドの項目（スライドの番号順）・追加ページの項目 {index, add, el}・今の印を付けた項目（出していなければ null）。go と fitStage が見るので、ここで宣言する
    let rendered = false;                                        // 舞台に一度でも描いたか
    let memoEl = null, memoText = null, memoId = null, memoBase = '', exportBtn = null;           // メモの帯・その欄・欄が今映しているスライドの id（出していなければ null）。go と fitStage が見るので、ここで宣言する
    let ownBtn = null, ownHead = null, ownText = null, ownId = null, ownOpen = false, ownBase = '';    // 自分用のメモ（開閉は保存しない。N を閉じる・読み直すと閉じた状態）
    const memoStore = createMemoStore(pageKey());                // メモの保存（欄ごとのキー）
    const indexOf = id => slides.findIndex(s => s.id === id);

    // ---- 舞台の置き方 ----
    // ノートを開いているときは、その幅を除いた領域に置く。中身の CSS（#stage の位置）に頼らず、style で決める
    function notesWidth() {
      const notes = document.querySelector('.sp-notes');
      return notes ? notes.getBoundingClientRect().width : 0;
    }
    // 一覧つきの画面の左の列の幅（出していなければ 0）
    function sideWidth() {
      return sideEl ? sideEl.getBoundingClientRect().width : 0;
    }
    // メモの帯の高さ（出していなければ 0）
    function memoHeight() {
      return memoEl ? memoEl.getBoundingClientRect().height : 0;
    }
    // 中央の領域：左の列・ノート・メモの帯を除いた所。舞台・操作ボタンの帯・知らせ・リンクを表示は、どれもこれを基準に置く
    function centerArea() {
      const left = sideWidth();
      return { left, width: Math.max(1, window.innerWidth - left - notesWidth()), top: 0, height: Math.max(1, window.innerHeight - memoHeight()) };
    }
    function fitStage() {
      placeMemo();                                               // 帯の左右を、左の列・ノートの出入りに合わせる
      const area = centerArea();
      const availW = area.width;
      const availH = area.height;
      controls.style.bottom = memoHeight() + 'px';               // 操作ボタンの帯は、メモの帯の上に置く
      const k = Math.min(availW / STAGE_W, availH / STAGE_H);
      const s = stage.style;
      s.position = 'absolute';
      s.margin = '0';
      s.left = area.left + (availW - STAGE_W * k) / 2 + 'px';
      s.top = area.top + (availH - STAGE_H * k) / 2 + 'px';
      s.transformOrigin = '0 0';
      s.transform = `scale(${k})`;
      stageScale = k;
      if (writing) writing.layout();                                     // 線の層も、舞台と同じ位置・同じ縮小に置く。文字の欄は決めて閉じ、小さな帯は置き直す
      updatePaper();                                             // 追加ページの紙も、舞台と同じ位置・同じ縮小に置き直す
      placeToast();                                              // 操作ボタンの帯の高さが変わったかもしれない（幅・ノートの開閉）ので、知らせを置き直す
      layoutLinkMarks();                                         // 印の文字を、要素の新しい位置に合わせる
      layoutLinkView();                                          // リンクを表示が開いていれば、枠を要素の新しい位置に合わせる
    }

    // 舞台に描く（描画は render を呼ぶだけ。約束 §3.2）。例外を投げたら、舞台に代わりの表示を出し、警告と知らせを出す。
    // 場所（cur・hash・直近の場所）は呼ぶ側が通常どおり更新するので、そのスライドを越えて進める
    function renderMain(index, step) {
      try {
        window.slideDeck.render(index, step, stage);
      } catch (e) {
        const id = slides[index].id;
        const name = typeof id === 'string' && id ? id : `${index + 1}枚目`;
        console.warn(`プレイヤー：${name} を描けませんでした`, e);
        stage.textContent = '';
        stage.appendChild(el('div', 'sp-render-error', MSG_RENDER_FAILED(name)));
        toast(MSG_RENDER_FAILED(name));
      }
    }

    // URL の hash に書く形。ID が約束の形でないスライドは位置（1 から数える旧形式）で書く（再読み込みで同じスライドが開く）
    const hashOf = (index, step) => formatHash(isRef(slides[index].id) ? slides[index].id : String(index + 1), step);

    // ---- 追加ページ ----
    // 並びの表示の名前：1つ目は「（追加ページ）」、2つ目から「（追加ページ 2）」（その元のスライドの中での順）
    function addLabel(index, add) {
      const n = addsOf(index).indexOf(add) + 1;
      return n <= 0 ? '' : n === 1 ? '（追加ページ）' : `（追加ページ ${n}）`;
    }
    // デッキの順のページ：すべてのスライドと、その直後の追加ページ
    function pageSeq() {
      const out = [];
      slides.forEach((_, i) => {
        out.push({ index: i, add: null });
        for (const add of addsOf(i)) out.push({ index: i, add });
      });
      return out;
    }
    // 位置の表示「12 / 28　段階 1/3」「3（追加ページ） / 9」
    function positionText() {
      if (curAdd) return `${cur + 1}${addLabel(cur, curAdd)} / ${slides.length}`;
      const steps = slides[cur].steps;
      return `${cur + 1} / ${slides.length}` + (steps > 0 ? `　段階 ${curStep}/${steps}` : '');
    }
    // 順の次・前のページ（なければ null）。{index, step, add}：スライドの最後の段階 → 追加ページ（並びの順）→ 次のスライドの段階0
    function nextPage() {
      const list = addsOf(cur);
      if (curAdd === null && list.length) return { index: cur, step: slides[cur].steps, add: list[0] };
      if (curAdd !== null && list.indexOf(curAdd) + 1 < list.length) return { index: cur, step: slides[cur].steps, add: list[list.indexOf(curAdd) + 1] };
      return cur < slides.length - 1 ? { index: cur + 1, step: 0, add: null } : null;
    }
    function prevPage() {
      const list = addsOf(cur), k = curAdd === null ? -1 : list.indexOf(curAdd);
      if (k > 0) return { index: cur, step: slides[cur].steps, add: list[k - 1] };
      if (k === 0) return { index: cur, step: slides[cur].steps, add: null };
      if (cur === 0) return null;
      const before = addsOf(cur - 1);
      return { index: cur - 1, step: slides[cur - 1].steps, add: before.length ? before[before.length - 1] : null };
    }
    // 追加ページの紙 .sp-paper：追加ページにいるときだけ、舞台と同じ位置・同じ縮小で出す
    let paperEl = null;
    function updatePaper() {
      if (!curAdd) { if (paperEl) paperEl.style.display = 'none'; return; }
      if (!paperEl) {
        paperEl = el('div', 'sp-paper');
        paperEl.setAttribute('aria-hidden', 'true');
        document.body.appendChild(paperEl);
      }
      const s = stage.style;
      Object.assign(paperEl.style, { left: s.left, top: s.top, transformOrigin: '0 0', transform: s.transform, width: STAGE_W + 'px', height: STAGE_H + 'px', display: 'block' });
    }
    function addedPagesChanged() {
      syncSideAdds();
    }
    // 白紙を足す：今のページのすぐ後ろ（追加ページの上ならその後ろ、スライドの上ならそのスライドの追加ページの先頭）
    function addPage() {
      const saved = new Set(places.snapshot().items.map(p => p.add).filter(Boolean));     // 保存した場所に残る識別子は使わない
      let id;
      do { id = 'x' + addCounter++; } while (saved.has(id) || addsOf(cur).includes(id));
      const list = adds.get(cur) || [];
      list.splice(curAdd === null ? 0 : list.indexOf(curAdd) + 1, 0, id);
      adds.set(cur, list);
      addedPagesChanged();
      go(cur, slides[cur].steps, 'order', false, id);
    }
    // 今の追加ページを消し、前のページへ戻る。書いたものごと消すので、askConfirm のときは確かめる
    function removeAddedPage(askConfirm) {
      if (curAdd === null) return false;
      writing.commitText();                                      // 入力中の文字は先に確定する（確認の判断に入れる）
      if (askConfirm && writing.count() > 0 && !window.confirm(MSG_REMOVE_ADDED)) return false;
      const id = curAdd, index = cur;
      const back = prevPage();
      const list = addsOf(index).filter(x => x !== id);
      if (list.length) adds.set(index, list); else adds.delete(index);
      addedPagesChanged();
      go(back.index, back.step, 'order', false, back.add);
      writing.drop('a:' + id);
      return true;
    }

    // ---- 移動はすべて go を通る ----
    // 動きの途中の決まり：重なりを開く入口（?・O・L・補足）は先に settleMotion で動きを終える（動きの層が重なりにかぶらないように）。
    //   描画待ち（unpainted）の間に受けた L は、確定してから読む（古い要素を新しいスライドの links と組み合わせないため）。
    //   舞台のクリック・舞台の中の Enter は、確定したうえで無効にする（受けた時点で描画待ちだったかで決め、ブラウザの既定の動きも止める）
    // how："order"（↑↓ など規定の順序で動く）・"jump"（Shift・Home・End など、順序によらない移動）は直近の場所に記録する
    //      （別のスライドなら足し、同じスライドで段階だけなら今の場所を書き換える）。
    //      "place"（←→、ページに着いたとき）は並びを変えない（呼ぶ側が並びを合わせてある）。
    // どの場合も最後に、hash と今いる場所の識別子（history.state）を書く
    // entry：規定の順序で次のスライドへ進む操作（moveInOrder・moveBySlide の次へ）だけが true にする。入場は、別のスライドへ移ったときだけ
    function go(index, step, how, entry = false, add = null) {
      index = Math.min(Math.max(index, 0), slides.length - 1);
      if (add !== null && !addsOf(index).includes(add)) add = null;
      step = add !== null ? slides[index].steps : Math.min(Math.max(step, 0), slides[index].steps);
      commitMemo();                                              // 書きかけのメモは、移る前に今のスライドへ保存する（欄の blur には頼らない）
      if (overviewEl) closeOverview();                           // 一覧は開いたときの場所を映したもの。場所が変わるなら閉じる（ブラウザの戻る・進むなど）
      if (linkViewEl) closeLinkView();                           // リンクを表示・補足も、そのスライドのものなので同じ
      if (moreEl) closeMore();
      // 描画は render を呼ぶだけ（約束 §3.2）。着いたときの処理で、いま出ている所と同じなら描き直さない
      // （popstate と hashchange が続くときなどに、動画などを最初からにしないため。並びの処理は毎回行う）
      // 追加ページへ・から移るときは、舞台がすでにそのスライドの最後の段階なら描き直さない（舞台には触れない）
      const stageSame = rendered && !unpainted && stageAt.index === index && stageAt.step === step;
      const repaint = add !== null || curAdd !== null ? !stageSame : !(how === 'place' && rendered && index === cur && step === curStep);
      const kind = repaint ? motionKind(index, add) : 'none';    // 動きは、押したキーではなく、移った結果で決める（cur を更新する前に見る）
      const style = entry && repaint && index !== cur && add === null ? entryStyle() : null;
      const seq = ++goSeq;
      if (repaint) { entering = style; entryId = 0; if (style) entries.arm(style); else entries.reset(); }
      const wasAdd = curAdd !== null;
      cur = index;
      curStep = step;
      curAdd = add;
      // 描画とリンクの印は paintStage で行う。動かすときは、View Transitions の更新の中（少し後）で行う。
      // cur・curStep・直近の場所・hash・位置の表示・ノートは、動かすときもその場で更新する
      if (repaint) unpainted = true;
      writing.cut();                                                 // 書いている途中の線は、ここで切る（次のスライドに続きが混ざらない）
      if (kind !== 'none') startMotion(kind);
      else if (repaint) { stopMotion(); paintStage(); lastMotion = { kind: 'none', done: Promise.resolve() }; }
      else if (!unpainted) paintStage();                         // 描かなかったときも、リンクの印は付け直す（描画待ちがあるなら、その更新が描く）
      if (!repaint && (add !== null || wasAdd)) lastMotion = { kind: 'none', done: Promise.resolve() };   // 追加ページへ・からの移動は動きなし
      updatePaper();                                             // 追加ページの紙は、描画待ちがあっても今の位置のとおりに出す・隠す
      // 入場は、送りの動きが終わってから再生する（送りがなければすぐ）。その間に次の移動があれば、この再生はしない
      if (style) lastMotion.done.then(() => { if (seq === goSeq) entries.play(entryId); });
      if (how === 'order' || how === 'jump') record(slides[cur].id, curStep, curAdd);
      writeLocation(hashOf(cur, curStep));
      updatePosition();
      updateSide();
      updateNotes();
      updateMemo();
    }

    // ---- 切り替えの動き（ブラウザの View Transitions）----
    // 動きの種類：'next'（隣へ・先）・'prev'（隣へ・前）・'jump'（隣でない）・'none'（動かさない）。index は移る先（cur は今の位置）
    function motionKind(index, add = null) {
      if (add !== null || curAdd !== null) return 'none';        // 追加ページへ・から移るときは動かさない（紙は舞台の外に重ねるので、舞台だけの動きに乗らない）
      if (!rendered || index === cur) return 'none';             // 初めての描画・同じスライド（段階だけ）は動かさない
      if (!document.startViewTransition || !sendAllowed()) return 'none';
      if (sideEl && isWebKit()) return 'none';                   // WebKit は、名前を付けた左の列の新しい写しを描かず、列が消える。列を出している間は動かさない（すぐに切り替える）
      if (overlays.top()) return 'none';                         // 重なりが開いている間は動かさない（動きの層が重なりを隠すため）。逆に動いている最中に重なりを開くときは settleMotion で終える
      if (Math.abs(index - cur) !== 1) return 'jump';
      return index > cur ? 'next' : 'prev';
    }

    let unpainted = false;                                       // 最新の cur・curStep をまだ舞台に描いていない
    let motion = null;                                           // 動いている最中の動き：{kind}
    let lastMotion = { kind: 'none', done: Promise.resolve() };  // 最後に選んだ動き（試験用の窓口が返す）
    let arrival = { played: false, done: Promise.resolve() };    // 着いたときのフェードイン（playArrival の結果）
    const entries = createEntry(stage, () => layoutLinkMarks());   // 入場。終わったら、リンクの印を止まった位置に置き直す
    let entering = null;                                         // 次に描いたときに用意する入場の型（なければ null）
    let entryId = 0;                                             // 用意した入場の番号（play に渡す）
    // 入場を確定する。描く前の予約（entering）も取り消す（描いたあとで入場が始まらないように）
    function settleEntry() {
      entering = null;
      entries.settle();
    }
    let goSeq = 0;                                               // go の回数（古い移動の再生を止める）
    const pointer = createPointer(stage, {                       // 指す層
      point: () => pointOn() && canHover(), still: () => !motionAllowed(), light: lightOn, scale: () => stageScale,
    });
    const writing = createWriting({                              // 書き込み。どのデッキでも使える
      stage,
      pageKey: () => (curAdd ? 'a:' + curAdd : 's:' + String(slides[cur].id)),
      isAdded: () => curAdd !== null,
      onAddPage: addPage,
      onRemovePage: () => removeAddedPage(true),
      styles: { get: () => settings.get().ink, set: ink => settings.set({ ink }) },
      onUndoEmpty: () => removeAddedPage(false),                 // 追加ページで戻すものがなければ、そのページごと消す
      onChange(active) {
        if (active) {
          settleEntry();
          pointer.hide();
          if (stage.contains(document.activeElement)) document.activeElement.blur();   // 舞台のリンクに焦点を残さない（Enter で開かないように）
        }
        buttons.writing.setAttribute('aria-pressed', String(active));
      },
    });

    // 舞台に、最新の cur・curStep を描き、リンクの印を付ける。描くものがなければ、印の付け直しだけ
    function paintStage() {
      if (unpainted) {
        unpainted = false;
        renderMain(cur, curStep);
        rendered = true;
        stageAt.index = cur;
        stageAt.step = curStep;
        if (entering) { entryId = entries.prepare(entering); entering = null; }   // 描いた直後に、入る前の姿にしておく
        writing.show();                                              // このスライドの線を出す
      }
      if (curAdd === null) markLinks();                          // 描いたあとで、舞台のリンクの要素に印を付ける（追加ページには印を付けない）
      layoutLinkMarks();
    }

    let jumpMsgEl = null;                                        // 「URLジャンプします」（ジャンプの動きの間だけ）
    function showJumpMessage() {
      removeJumpMessage();
      const r = stage.getBoundingClientRect();
      jumpMsgEl = el('div', 'sp-jumpmsg', MSG_JUMP);
      jumpMsgEl.setAttribute('aria-hidden', 'true');
      Object.assign(jumpMsgEl.style, { left: r.left + 'px', top: r.top + 'px', width: r.width + 'px', height: r.height + 'px' });
      document.body.appendChild(jumpMsgEl);
    }
    function removeJumpMessage() {
      if (jumpMsgEl) { jumpMsgEl.remove(); jumpMsgEl = null; }
    }
    const clearMotionClasses = () => document.documentElement.classList.remove('sp-vt-stage', 'sp-vt-root', 'sp-mv-next', 'sp-mv-prev', 'sp-mv-jump');

    // 動きを終わらせ、描画待ちがあれば最新の舞台と印を描く。いつ呼んでもよい（動いていなくて描画待ちもなければ何もしない）。
    // stopMotion だけでは、飛ばした動きの更新が何もしない（motion !== mine）ので、描画待ちが残る
    function settleMotion() {
      stopMotion();
      if (unpainted) paintStage();
      settleEntry();                                             // 入場の途中の状態も、描く前の予約も終える
      if (pointer) pointer.hide();                               // 重なりを開く前に光を消す
    }

    // 動いている最中の動きを飛ばす（次の移動が来たとき）。更新がまだなら、その更新は何もしない（motion を空にするため）
    function stopMotion() {
      if (!motion) return;
      const vt = motion.vt;
      motion = null;
      clearMotionClasses();
      removeJumpMessage();
      if (vt) { try { vt.skipTransition(); } catch (e) { /* 飛ばせなくても、描画は paintStage が行う */ } }
    }

    function startMotion(kind) {
      stopMotion();
      const mine = { kind, vt: null };
      motion = mine;
      document.documentElement.classList.add(isWebKit() ? 'sp-vt-root' : 'sp-vt-stage', 'sp-mv-' + kind);   // 名前は、古い画面を撮る前に付ける
      const finish = () => {
        if (motion !== mine) return;                             // 飛ばされた動きは、次の動きが引き継ぐ
        motion = null;
        clearMotionClasses();
        removeJumpMessage();
        if (unpainted) paintStage();                             // 念のため：更新が走らなかったときも、最新の画面にする
      };
      try {
        // 飛ばされた動きの更新は何もしない（次の動きか、その場の描画が最新を描く。描くと、同じ画像が流れてしまう）
        mine.vt = document.startViewTransition(() => {
          if (motion !== mine) return;
          paintStage();
          if (kind === 'jump') showJumpMessage();
        });
      } catch (e) {
        motion = null;
        clearMotionClasses();
        paintStage();
        lastMotion = { kind: 'none', done: Promise.resolve() };
        return;
      }
      mine.vt.ready.catch(() => {});
      mine.vt.updateCallbackDone.catch(e => console.warn('プレイヤー：切り替えの動きの更新で例外が出ました', e));
      lastMotion = { kind, done: mine.vt.finished.then(finish, finish) };
    }

    // 位置の表示「12 / 28　段階 1/3」（操作ボタンの帯の .sp-pos）。あれば更新する
    function updatePosition() {
      const el = document.querySelector('.sp-pos');
      if (!el) return;
      el.textContent = positionText();
    }

    // ページに着いたときの処理（arrive）と ←→ に、このデッキの見せ方を渡す
    view = {
      kind: 'deck',
      msgBadHash: MSG_BAD_HASH,
      read(hash) {
        const r = parseHash(hash, slides);
        return r.kind === 'ok' ? { kind: 'ok', ref: slides[r.index].id, step: r.step } : r;
      },
      resolve(ref, step, add = null) {
        const i = indexOf(ref);
        if (i < 0) return null;
        if (add && addsOf(i).includes(add)) return { ref, step: slides[i].steps, add };
        return { ref, step: add ? slides[i].steps : Math.min(step, slides[i].steps) };        // 追加ページがもうなければ、元のスライドの最後の段階
      },
      first: () => ({ ref: slides[0].id, step: 0 }),
      sameSlide: (a, b, addA = null, addB = null) => a === b && (addA || null) === (addB || null),
      liveAdd(ref, add) {
        const i = indexOf(ref);
        return i >= 0 && add && addsOf(i).includes(add) ? add : null;
      },
      show(ref, step, add = null) {
        const i = indexOf(ref);
        if (i >= 0) {
          const live = add && addsOf(i).includes(add) ? add : null;
          go(i, add && !live ? slides[i].steps : step, 'place', false, live);
          return;
        }
        go(0, 0, 'place');                                       // デッキが書き換わって、その ID がもうない
        toast(MSG_PLACE_GONE);
      },
    };

    // ---- 画面の部品 ----

    settings.load();
    const info = window.slideDeck.info;

    // H で開く目次：info.home を、このページからの相対 URL として読み、デッキの ID を hash に付ける。
    // 開いてよい種類（file・http・https）でなければ、H は効かない（ボタンも出さない）
    const homeUrl = (() => {
      if (typeof info.home !== 'string' || !info.home) return null;
      try {
        const u = new URL(info.home, location.href);
        if (!LINK_PAGE_SCHEMES.includes(u.protocol)) return null;
        if (typeof info.id === 'string' && info.id) u.hash = info.id;
        return u.href;
      } catch (e) { return null; }
    })();
    const goHome = () => { if (homeUrl) openPage(homeUrl); };

    // ---- 操作ボタン ----

    // 操作ボタンの帯 .sp-controls
    const controls = el('div', 'sp-controls');
    controls.setAttribute('role', 'toolbar');
    controls.setAttribute('aria-label', '操作ボタン');
    const buttons = {};
    function addButton(id, label, run) {
      const b = makeButton(label, run);
      buttons[id] = b;
      controls.appendChild(b);
      return b;
    }
    controls.appendChild(el('span', 'sp-pos'));
    addButton('prev', '↑ 前', () => moveInOrder(-1));
    addButton('next', '↓ 次', () => moveInOrder(1));
    addButton('back', '← 戻る', () => movePlace(-1));
    addButton('forward', '→ 進む', () => movePlace(1, () => moveInOrder(1)));
    addButton('overview', 'O 一覧', () => { if (commands.overview) commands.overview(); });
    addButton('side', 'T 一覧つき', () => toggleSide());
    addButton('notes', 'N ノート', () => toggleNotes());
    addButton('memo', 'M メモ', () => toggleMemo());
    addButton('links', 'L リンク', () => { if (commands.links) commands.links(); });
    if (homeUrl) addButton('home', 'H 目次', goHome);
    addButton('pdf', 'P PDF', printDeck);
    addButton('writing', 'D 書き込み', () => writing.toggle());
    addButton('fullscreen', 'F 全画面', toggleFullscreen);
    addButton('help', '?', () => toggleHelp()).setAttribute('aria-label', '操作の一覧');
    buttons.notes.setAttribute('aria-pressed', 'false');
    buttons.memo.setAttribute('aria-pressed', 'false');
    buttons.side.setAttribute('aria-pressed', 'false');
    buttons.writing.setAttribute('aria-pressed', 'false');
    document.body.appendChild(controls);
    toastAvoid = controls;                                       // 知らせは、帯が出ているとき、その上に出す（placeToast）
    toastLift = memoHeight;                                      // 知らせは、メモの帯が出ているとき、その上に出す（placeToast）
    toastArea = centerArea;                                      // 知らせは、中央の領域の真ん中に出す（placeToast）

    // 帯をキーボードで押したボタン（Enter・Space で押したとき。マウス・タッチで押したときは焦点を外すので、残らない）。
    // 焦点が帯に残っている間、移動のキーはこのボタンを押し直さず、焦点を外してから動く（キー操作の listener）
    let pressedByKey = null;
    for (const b of Object.values(buttons)) b.addEventListener('click', e => { pressedByKey = e.detail === 0 ? b : null; });

    // 出し方：auto はマウスの移動・タッチで出し、3 秒動きがなければ隠す。always は常に出し、never は出さない。
    // auto でも、マウスが操作ボタンの上にある間、または操作ボタンの中に焦点がある間は隠さない（離れてから 3 秒で隠す）
    let hideTimer = 0, pointerOnControls = false;
    const setControlsOn = on => { controls.classList.toggle('sp-on', on); placeToast(); };      // 帯の出入りに合わせて、知らせの高さも変える
    function showControls() {
      clearTimeout(hideTimer);
      const mode = settings.get().controls;
      if (mode === 'never') { setControlsOn(false); pointerOnControls = false; return; }
      setControlsOn(true);
      if (mode === 'auto') {
        hideTimer = setTimeout(() => {
          if (!pointerOnControls && !controls.contains(document.activeElement)) setControlsOn(false);
        }, CONTROLS_HIDE_MS);
      }
    }
    // 出し方を反映する。auto は、読み込み直後は隠し（reveal なし）、選んだ直後は出す（reveal あり）
    function applyControls(reveal) {
      if (settings.get().controls === 'auto' && !reveal) {
        clearTimeout(hideTimer);
        setControlsOn(false);
      } else {
        showControls();
      }
    }
    // 指で払う操作：キーと同じ動き（actionFor）を、払った向きの矢印キーとして呼ぶ（Shift なし）。
    // 下の showControls の listener より先に付ける：払う前に帯が隠れていたかを、触れた時点（帯が出る前）で覚えるため。
    // 隠れていたなら、払ったあとに隠し直す（払うたびに帯が出ないように）。出ていたなら、そのまま
    let hiddenBeforeSwipe = false;
    createSwipe({
      enabled: () => !writing.active(),                              // 書き込みの間は払いを扱わない
      onStart: () => { hiddenBeforeSwipe = !controls.classList.contains('sp-on'); },
      onSwipe(dir) {
        if (hiddenBeforeSwipe) { clearTimeout(hideTimer); setControlsOn(false); }
        const action = actionFor({ key: SWIPE_KEYS[dir], shiftKey: false });
        if (action) action();
      },
    });
    // 光を使っている間は、マウスの移動で帯を出すのは画面の下の端の近くか帯の上だけ（なぞるたびに帯が出ないように）
    const revealByPointer = e => {
      if (writing.active()) return;                                  // 書き込みの間は、線を引くたびに帯が出ないように
      if (e.type === 'pointermove' && e.pointerType === 'mouse' && pointer.lightActive()
        && e.clientY < window.innerHeight - CONTROLS_EDGE_PX && !pointerOnControls && !controls.contains(e.target)) return;
      showControls();
    };
    for (const type of ['pointermove', 'pointerdown', 'touchstart']) {
      document.addEventListener(type, revealByPointer, { passive: true, capture: true });
    }
    controls.addEventListener('pointerenter', () => { pointerOnControls = true; });
    controls.addEventListener('pointerleave', () => { pointerOnControls = false; showControls(); });      // 離れたところから 3 秒を数える
    controls.addEventListener('focusin', showControls);          // Tab で入ったボタンが、隠れないように
    controls.addEventListener('focusout', e => {
      if (e.target === pressedByKey) pressedByKey = null;        // 焦点が離れたボタンは、「キーボードで押したまま」ではなくなる
      if (!controls.contains(e.relatedTarget)) showControls();   // 焦点が外れたところから 3 秒を数える
    });

    // ---- ノート ----

    // ノート .sp-notes：右に出し、開閉の状態を保存する。舞台は fitStage が残りの幅に置く
    let notesEl = null, notesTitle = null, notesTime = null, notesBody = null, notesShown = -1;
    function updateNotes() {
      if (!notesEl) return;
      const s = slides[cur];
      if (curAdd !== null) {                                     // 追加ページ：見出しだけ。ノートの中身も自分用のメモもない
        notesTitle.textContent = addLabel(cur, curAdd);
        notesTime.textContent = '';
        notesTime.hidden = true;
        notesBody.textContent = '';
        notesBody.classList.add('sp-notes-empty');
        notesShown = -1;
        updateOwn();
        return;
      }
      notesTitle.textContent = typeof s.title === 'string' && s.title ? `${s.id}　${s.title}` : s.id;
      const minutes = s.minutes;
      const hasMinutes = typeof minutes === 'number' && Number.isFinite(minutes) && minutes > 0;
      notesTime.textContent = hasMinutes ? `目安 ${minutes} 分` : '';
      notesTime.hidden = !hasMinutes;
      const text = typeof s.notes === 'string' ? s.notes : '';
      const has = text.trim() !== '';
      notesBody.textContent = has ? text : MSG_NO_NOTES;
      notesBody.classList.toggle('sp-notes-empty', !has);
      if (notesShown !== cur) { notesBody.scrollTop = 0; notesShown = cur; }    // 段階だけの移動では、読んでいる位置を保つ
      updateOwn();
    }
    // 自分用のメモ：今のスライドの own を入れる。書いている最中の欄（同じスライドのまま）は上書きしない
    function updateOwn() {
      if (!notesEl) return;
      const hide = curAdd !== null;                              // 追加ページでは自分用のメモの部品を隠し、保存には触れない
      ownBtn.style.display = hide ? 'none' : '';
      if (ownHead) ownHead.style.display = ownText.style.display = hide ? 'none' : '';
      if (hide || !ownOpen) return;
      const id = slides[cur].id;
      const text = memoStore.get(id, 'own');
      if (ownId !== id) { ownId = id; ownText.value = ownBase = text; }
      else if (document.activeElement !== ownText) { ownText.value = ownBase = text; }
    }
    function setOwn(open) {
      if (!notesEl || open === ownOpen) return;
      ownOpen = open;
      if (open) {
        ownHead = el('div', 'sp-notes-own-head', MSG_OWN_HEAD);
        ownText = el('textarea', 'sp-notes-memo');
        ownText.maxLength = MEMO_MAX_CHARS;
        ownText.setAttribute('aria-label', MSG_OWN_HEAD);
        let composing = false;                                   // 変換中の Esc は欄から抜けない（帯と同じ）
        ownText.addEventListener('compositionstart', () => { composing = true; });
        ownText.addEventListener('compositionend', () => { composing = false; });
        ownText.addEventListener('input', () => { memoStore.set(ownId, 'own', ownText.value); });
        ownText.addEventListener('blur', () => memoStore.flush());
        ownText.addEventListener('keydown', e => {
          if (e.key === 'Escape' && !e.isComposing && !composing && e.keyCode !== 229) { e.preventDefault(); ownText.blur(); }
        });
        ownId = null;
        ownBtn.parentNode.append(ownHead, ownText);
      } else {
        commitMemo();
        ownHead.remove(); ownText.remove();
        ownHead = ownText = ownId = null;
      }
      ownBtn.textContent = open ? MSG_OWN_CLOSE : MSG_OWN_OPEN;
      updateOwn();
    }
    function setNotes(open, save) {
      if (open === !!notesEl) return;
      settleEntry();                                             // 舞台の大きさが変わる前に、入場を確定する
      if (open) {
        notesEl = el('div', 'sp-notes');
        notesEl.setAttribute('role', 'complementary');
        notesEl.setAttribute('aria-label', 'ノート');
        const head = el('div', 'sp-notes-head');
        notesTitle = el('div', 'sp-notes-title');
        notesTime = el('div', 'sp-notes-time');
        head.append(notesTitle, notesTime);
        notesBody = el('div', 'sp-notes-body');
        const own = el('div', 'sp-notes-own');
        ownBtn = makeButton(MSG_OWN_OPEN, () => setOwn(!ownOpen));
        ownBtn.classList.add('sp-notes-own-toggle');
        own.appendChild(ownBtn);
        notesEl.append(head, notesBody, own);
        notesShown = -1;
        document.body.appendChild(notesEl);
      } else {
        commitMemo();                                            // 自分用の欄に書きかけがあれば、閉じる前に保存する
        notesEl.remove();
        notesEl = notesTitle = notesTime = notesBody = null;
        ownBtn = ownHead = ownText = ownId = null;
        ownOpen = false;
      }
      controls.classList.toggle('sp-beside-notes', open);
      buttons.notes.setAttribute('aria-pressed', String(open));
      if (save) settings.set({ notes: open });
      updateNotes();
      applySide();                                               // ノートの幅で中央の領域が変わるので、列を出せるか決め直す（舞台も置き直す）
    }
    const toggleNotes = () => setNotes(!notesEl, true);

    // ---- メモの帯（M）----

    // 帯 .sp-memo：舞台の下に出す。欄 .sp-memo-text に書くと、今のスライドの id に結び付けて保存する（memoStore。欄ごとのキー）。
    // 書いた文字は、書いたスライドに付ける：移る前に go が commitMemo で保存してから、移った先の中身を入れる（updateMemo）。
    // 開閉は設定 memo に保存する。実際に出すかは高さで決まる（applySide。高さが足りないだけでは設定を書き換えない）
    const memoBandHeightIfShown = () => Math.min(MEMO_BAND_MAX_PX, Math.max(MEMO_BAND_MIN_PX, window.innerHeight * MEMO_BAND_VH / 100));
    const memoRoom = () => window.innerHeight - memoBandHeightIfShown() >= MEMO_MIN_CENTER_PX;
    let failToasted = false;
    memoStore.onFail(() => { if (!failToasted) { failToasted = true; toast(MSG_MEMO_FAILED); } });

    // 欄の中身を、書いているスライドへ保存する（待たずに書く）
    function commitMemo() {
      // 基準の値（最後に読み込んだ値・最後に保存できた値）と違う欄だけ書く：打っていない古い欄で、ほかのタブの新しい保存を戻さない
      // 追加ページの間は、欄を空にして読み取り専用にしている（memoId は null）ので、保存に触れない
      if (memoEl && memoId !== null && memoText.value !== memoBase) memoStore.set(memoId, 'shared', memoText.value);
      if (ownText && ownId !== null && curAdd === null && ownText.value !== ownBase) memoStore.set(ownId, 'own', ownText.value);
      memoStore.flush();
      markSideMemo();
      updateExport();
    }
    // 欄を今のスライドのメモにする（書いている途中の欄は触らない：別のスライドへ移るときは commitMemo が先に済んでいる）
    function updateMemo() {
      if (!memoEl) return;
      memoText.readOnly = curAdd !== null;
      if (curAdd !== null) {                                     // 追加ページ：書けない（保存の読み書きをしない）
        memoId = null;
        memoText.value = memoBase = '';
        memoText.placeholder = MSG_NO_MEMO_ADDED;
        updateExport();
        return;
      }
      memoText.placeholder = '';
      const id = slides[cur].id;
      const text = memoStore.get(id, 'shared');
      if (memoId !== id) { memoId = id; memoText.value = memoBase = text; }
      else if (document.activeElement !== memoText) { memoText.value = memoBase = text; }    // 焦点のある欄は、ほかのタブの値で上書きしない
      updateExport();
    }
    // 書き出す：先に保存を済ませ、デッキにあるスライドの shared だけを、デッキの順に Markdown にする（own は入れない）
    function sharedMemos() {
      const all = memoStore.all('shared'), out = [];
      slides.forEach((s, i) => { const t = all.get(String(s.id)); if (t) out.push({ i, text: t }); });
      return out;
    }
    function updateExport() {
      if (exportBtn) exportBtn.disabled = sharedMemos().length === 0;
    }
    function exportMemo() {
      commitMemo();
      const items = sharedMemos();
      if (!items.length) return;
      const md = items.map(m => `## ${m.i + 1}　${slideTitleOf(m.i)}\n\n${m.text}\n`).join('\n');
      const deckTitle = window.slideDeck.info && typeof window.slideDeck.info.title === 'string' ? window.slideDeck.info.title : '';
      const name = (deckTitle ? `${deckTitle}-メモ` : 'メモ').replace(/[\/\\:*?"<>|]/g, '_') + '.md';
      const url = URL.createObjectURL(new Blob([md], { type: 'text/markdown;charset=utf-8' }));
      const a = el('a');
      a.href = url; a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    }
    function setMemo(open, save) {
      if (open !== !!memoEl) {
        settleEntry();                                           // 舞台の大きさが変わる前に、入場を確定する
        if (open) {
          memoEl = el('div', 'sp-memo');
          memoEl.setAttribute('role', 'complementary');
          memoEl.setAttribute('aria-label', 'メモ');
          const head = el('div', 'sp-memo-head');
          head.appendChild(el('span', null, 'メモ'));
          exportBtn = makeButton('書き出す', exportMemo);
          exportBtn.classList.add('sp-memo-export');
          head.appendChild(exportBtn);
          memoText = el('textarea', 'sp-memo-text');
          memoText.maxLength = MEMO_MAX_CHARS;
          memoText.setAttribute('aria-label', 'メモ');
          let composing = false;                                 // 変換中（Safari は変換を終える Esc の keydown に isComposing を付けないことがある）
          memoText.addEventListener('compositionstart', () => { composing = true; });
          memoText.addEventListener('compositionend', () => { composing = false; });
          memoText.addEventListener('input', () => {
            memoStore.set(memoId, 'shared', memoText.value);
            markSideMemo();
            updateExport();
          });
          memoText.addEventListener('blur', () => memoStore.flush());
          memoText.addEventListener('keydown', e => {            // 欄の中のキーはプレイヤーが扱わない（ignoredKey）ので、Esc だけここで受ける
            if (e.key === 'Escape' && !e.isComposing && !composing && e.keyCode !== 229) { e.preventDefault(); memoText.blur(); }
          });
          memoEl.append(head, memoText);
          memoId = null;
          document.body.appendChild(memoEl);
        } else {
          commitMemo();
          memoEl.remove();
          memoEl = memoText = memoId = exportBtn = null;
          memoBase = '';
        }
        buttons.memo.setAttribute('aria-pressed', String(open));
        updateMemo();
      }
      if (save) settings.set({ memo: open });
      applySide();                                               // 帯の高さで中央の領域が変わるので、舞台を置き直す
    }
    function toggleMemo() {
      if (memoEl) { setMemo(false, true); return; }
      if (!memoRoom()) { toast(MSG_MEMO_LOW); return; }
      setMemo(true, true);
    }
    // 帯の左右は、左の列・ノートの出入りに合わせる（applySide が呼ぶ）
    function placeMemo() {
      if (!memoEl) return;
      memoEl.classList.toggle('sp-beside-notes', !!notesEl);
      memoEl.classList.toggle('sp-beside-side', !!sideEl);
    }
    memoStore.onSaved((id, field, text) => {                     // 保存できた値を基準にする（書けなかったときは呼ばれない：次の移動でまた書く）
      if (field === 'shared' && memoEl && id === memoId) memoBase = text;
      if (field === 'own' && ownText && id === ownId) ownBase = text;
    });
    memoStore.onChange((id, field) => {                          // ほかのタブが書いた：書いていない欄と左の列の印を、その値に合わせる
      if (field === null || field === 'shared') { updateMemo(); markSideMemo(); updateExport(); }
      if (field === null || field === 'own') updateOwn();
    });

    // ---- 一覧つきの画面（T）----

    // 左の列 .sp-side：全スライドの縮小（最後の段階）を縦に並べ、番号と題名を添える。節があれば節の初めに節の題 .sp-side-section。
    // 項目 .sp-side-item（data-index）は焦点を受けない（tabIndex = -1。マウスで押しても焦点は移さない）。押すとそのスライドの段階0へ（縮小一覧と同じ 'jump'）。
    // 今のスライドの項目に sp-current を付け、移るたびに列の中で見える所へ動かす（updateSide。焦点は動かさない）。出したときに一度描き、戻したら外す。
    // 設定 side は「出したいか」で、実際に出すかは広さで決まる（applySide）。広さが足りないだけでは設定を書き換えない
    const sideWidthIfShown = () => Math.min(SIDE_MAX_PX, Math.max(SIDE_MIN_PX, window.innerWidth * SIDE_VW / 100));
    const sideRoom = () => window.innerWidth >= CATALOG_MID_PX && window.innerWidth - sideWidthIfShown() - notesWidth() >= SIDE_MIN_CENTER_PX;

    // 項目の縮小の倍率を、枠の幅から決める（幅は画面の大きさで変わる）
    function layoutSide() {
      if (!sideEl || !sideItems.length) return;
      const k = sideItems[0].firstChild.getBoundingClientRect().width / STAGE_W;
      for (const item of sideItems) item.firstChild.firstChild.style.transform = `scale(${k})`;
    }

    // 今の印を cur の項目に付け替え、列の中で見える所まで動かす。mount：出した直後（印を付け直す）
    function updateSide() {
      if (!sideEl) return;
      const item = curAdd === null ? sideItems[cur] : (sideAddItems.find(x => x.index === cur && x.add === curAdd) || {}).el || sideItems[cur];
      if (sideMarked !== item) {
        const prev = sideMarked;
        if (prev) { prev.classList.remove('sp-current'); prev.removeAttribute('aria-current'); }
        sideMarked = item;
        item.classList.add('sp-current');
        item.setAttribute('aria-current', 'true');
      }
      item.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }

    // 左の列の追加ページの項目を、今の追加ページに合わせて作り直す（スライドの項目は触らない）。足す・消すたびに呼ぶ
    function syncSideAdds() {
      if (!sideEl) return;
      for (const x of sideAddItems) x.el.remove();
      sideAddItems = [];
      sideMarked = null;                                         // 印は updateSide が付け直す
      for (const item of sideItems) { item.classList.remove('sp-current'); item.removeAttribute('aria-current'); }
      slides.forEach((_, i) => {
        let after = sideItems[i];
        for (const add of addsOf(i)) {
          const item = el('div', 'sp-side-item sp-side-add');
          item.dataset.index = String(i);
          item.dataset.add = add;
          item.setAttribute('role', 'button');
          item.setAttribute('aria-label', `${i + 1}${addLabel(i, add)} / ${slides.length}　白紙`);
          item.tabIndex = -1;
          const frame = el('div', 'sp-side-frame');
          frame.appendChild(el('div', 'sp-side-blank', '白紙'));
          item.append(frame, el('div', 'sp-side-caption', addLabel(i, add)));
          item.addEventListener('mousedown', e => e.preventDefault());
          item.addEventListener('click', () => go(i, slides[i].steps, 'jump', false, add));
          after.after(item);
          after = item;
          sideAddItems.push({ index: i, add, el: item });
        }
      });
      updateSide();
    }

    // 左の列の ✎：帯のメモのあるスライドの題名の横に付ける（なければ外す）
    function markSideMemo() {
      if (!sideEl) return;
      const withMemo = memoStore.all('shared');
      sideItems.forEach((item, i) => {
        const has = withMemo.has(String(slides[i].id));
        item.classList.toggle('sp-has-memo', has);
        const mark = item.querySelector('.sp-side-memo');
        if (has && !mark) {
          const m = el('span', 'sp-side-memo', '✎');
          m.setAttribute('role', 'img');
          m.setAttribute('aria-label', 'メモあり');
          item.appendChild(m);
        } else if (!has && mark) {
          mark.remove();
        }
      });
    }

    function buildSide() {
      sideEl = el('div', 'sp-side');
      sideEl.setAttribute('role', 'group');
      sideEl.setAttribute('aria-label', 'スライドの一覧');
      sideItems = [];
      sideAddItems = [];
      sideMarked = null;
      let lastTitle;
      slides.forEach((slide, i) => {
        const title = sectionTitleOf(slide);
        if (title !== lastTitle) {
          if (title !== null) {
            const heading = el('div', 'sp-side-section', title);
            heading.setAttribute('role', 'heading');
            heading.setAttribute('aria-level', '2');
            sideEl.appendChild(heading);
          }
          lastTitle = title;
        }
        const item = el('div', 'sp-side-item');
        item.dataset.index = String(i);
        item.setAttribute('role', 'button');
        item.setAttribute('aria-label', `${i + 1} / ${slides.length}　${slideTitleOf(i)}`);
        item.tabIndex = -1;
        const { frame, broken } = buildThumbFrame(i, 'sp-side-frame', 1, '一覧つきの画面');      // 倍率は layoutSide が枠の幅から決める
        if (broken) item.classList.add('sp-thumb-broken');
        const caption = el('div', 'sp-side-caption', `${i + 1}　${slideTitleOf(i)}`);
        caption.title = caption.textContent;
        item.append(frame, caption);
        item.addEventListener('mousedown', e => e.preventDefault());            // 押しても焦点を移さない（キーは今までどおりメインのスライドを動かす）
        item.addEventListener('click', () => go(i, 0, 'jump'));
        sideItems.push(item);
        sideEl.appendChild(item);
      });
      document.body.appendChild(sideEl);
      syncSideAdds();
      layoutSide();
      markSideMemo();
    }

    // 出す・戻す。save：設定を書く（T のとき）。読み込み・画面の大きさ・ノートの開閉では書かない
    function setSide(open, save) {
      if (open !== !!sideEl) {
        settleEntry();                                           // 舞台の大きさが変わる前に、入場を確定する
        if (open) {
          buildSide();
        } else {
          sideEl.remove();                                       // 縮小の描画先もここで全部外れる
          sideEl = null;
          sideItems = [];
          sideAddItems = [];
          sideMarked = null;
        }
        controls.classList.toggle('sp-beside-side', open);
        buttons.side.setAttribute('aria-pressed', String(open));
        updateSide();
      }
      if (save) settings.set({ side: open });
    }

    // 設定と広さから、実際に出すかを決める（広さが足りなければ出さない。設定は書かない）。いつ呼んでもよく、舞台・帯・知らせ・リンクを新しい中央の領域に置き直す
    function applySide() {
      setSide(settings.get().side && sideRoom(), false);
      const wantMemo = settings.get().memo && memoRoom();        // 帯も、設定と高さから決める（高さが足りなければ出さない。設定は書かない）
      if (wantMemo !== !!memoEl) setMemo(wantMemo, false);
      layoutSide();
      fitStage();
    }

    // T：出ていれば戻す。出ていなければ出す（広さが足りなければ知らせ、設定は変えない）
    function toggleSide() {
      if (sideEl) { setSide(false, true); fitStage(); return; }
      if (!sideRoom()) { toast(MSG_SIDE_NARROW); return; }
      setSide(true, true);
      fitStage();
    }

    // ---- 操作の一覧（?）----

    // 操作の一覧 .sp-help：キーの一覧と、操作ボタンの出し方の選択。開いている間はほかのキーでスライドを動かさない
    const HELP_KEYS = [
      [['↓', 'PageDown', 'Space'], '次へ（段階があれば次の段階、なければ次のスライド）'],
      [['↑', 'PageUp'], '前へ（前の段階、なければ前のスライドの最後の段階）'],
      [['Shift＋↓'], '次のスライドの最初へ'],
      [['Shift＋↑'], '前のスライドの最後の段階へ'],
      [['←', '→'], '直近の場所を戻る・進む（先の場所がないときの → は ↓ と同じ）'],
      [['指で左へ払う', '右へ払う'], '→・← と同じ（iPhone・iPad）'],
      [['指で上へ払う', '下へ払う'], '↓・↑ と同じ'],
      [['Home', 'End'], '最初・最後のスライドへ'],
      [['O'], '縮小一覧を開く'],
      [['T'], '一覧つきの画面にする・戻す'],
      [['L'], 'リンクを表示する'],
      [['H'], '目次へ戻る', 'home'],
      [['N'], 'ノートを開く・閉じる'],
      [['M'], 'メモの帯を出す・隠す'],
      [['P'], 'PDF に書き出す（印刷の画面で「PDFに保存」を選ぶ。⌘P より確実）'],
      [['D'], '書き込みを始める・終える（書き込みの間は E で今のページの書き込みを全部消す）'],
      [['⌘Z', 'Ctrl＋Z'], '書き込みの間、ひとつ戻す（ページごと）'],
      [['右クリック'], '書き込みの間、その場所に文字を置く'],
      [['ダブルクリック', 'Delete・Backspace'], '書き込みの間、書いたものを選ぶ・選んだものを消す'],
      [['F'], '全画面にする・戻す'],
      [['?'], 'この一覧を開く・閉じる'],
      [['Esc'], '開いているものを閉じる'],
    ];
    function syncHelpChoices() {
      const helpEl = help.element();
      if (!helpEl) return;
      const mode = settings.get().controls;
      for (const b of helpEl.querySelectorAll('[data-sp-mode]')) b.setAttribute('aria-pressed', String(b.dataset.spMode === mode));
      const on = settings.get().motion;
      for (const b of helpEl.querySelectorAll('[data-sp-motion]')) b.setAttribute('aria-checked', String((b.dataset.spMotion === 'on') === on));
      const light = settings.get().light;
      for (const b of helpEl.querySelectorAll('[data-sp-light]')) b.setAttribute('aria-checked', String((b.dataset.spLight === 'on') === light));
    }
    function chooseMotion(on) {
      if (!on) settleEntry();
      settings.set({ motion: on });
      pointer.refresh();
      syncHelpChoices();
    }
    function chooseLight(on) {
      settings.set({ light: on });
      if (!on) pointer.hide();
      syncHelpChoices();
    }
    // 「あり／なし」の選択（role=radiogroup）。attr：data-sp-<attr> に on・off を入れる
    function onOffChoices(panel, title, attr, choose) {
      panel.appendChild(el('div', 'sp-help-section', title));
      const group = el('div', 'sp-help-choices');
      group.setAttribute('role', 'radiogroup');
      group.setAttribute('aria-label', title);
      for (const [key, label] of [['on', 'あり'], ['off', 'なし']]) {
        const b = makeButton(label, () => choose(key === 'on'));
        b.setAttribute('role', 'radio');
        b.setAttribute('data-sp-' + attr, key);
        group.appendChild(b);
      }
      panel.appendChild(group);
    }
    function chooseControls(mode) {
      settings.set({ controls: mode });
      applyControls(true);
      syncHelpChoices();
    }
    const help = createHelp({
      beforeOpen: settleMotion,
      rows: HELP_KEYS.filter(([, , only]) => only !== 'home' || homeUrl).map(([keys, text]) => [keys, text]),
      extra(panel) {
        panel.appendChild(el('div', 'sp-help-section', '操作ボタンの出し方'));
        const choices = el('div', 'sp-help-choices');
        choices.setAttribute('role', 'group');
        choices.setAttribute('aria-label', '操作ボタンの出し方');
        for (const mode of CONTROLS_MODES) {
          const b = makeButton(CONTROLS_LABELS[mode], () => chooseControls(mode));
          b.dataset.spMode = mode;
          choices.appendChild(b);
        }
        panel.appendChild(choices);
        onOffChoices(panel, '動き', 'motion', chooseMotion);
        if (pointOn()) onOffChoices(panel, '光', 'light', chooseLight);   // マウスの光は、指す層を選んだデッキだけ
      },
      onChange(open) {
        buttons.help.setAttribute('aria-pressed', String(open));
        if (open) syncHelpChoices();
      },
    });
    const toggleHelp = help.toggle;

    // ---- 縮小一覧（O）----

    // 縮小一覧 .sp-overview：上に直近の場所の列 .sp-recent（新しい順）、その下に節ごとの見出し .sp-section-title と
    // サムネイル .sp-thumb（data-index）。modal：開いている間、矢印は一覧の中の選択を動かす（← → も直近の場所ではない）。
    // Enter・クリックでそのスライドの段階0へ、Esc・O で閉じる。
    // サムネイルは開いたときに作り（1920×1080 の描画先を transform で縮めて、決まった大きさの枠に置き、最後の段階を描く）、
    // 閉じたら全部 DOM から外す。メインの舞台には描かない。
    let overviewThumbs = [], overviewSel = -1;

    // 直近の場所の項目の文字。同じデッキ：スライドの題名。別のページ：「ページ名：ID」。目次：「目次：デッキの ID」
    function recentLabel(p) {
      if (p.kind === 'catalog') return `目次：${p.ref}`;
      if (isOwn(p)) {
        const i = indexOf(p.ref), s = slides[i];
        const title = s && typeof s.title === 'string' && s.title ? s.title : p.ref;
        return p.add && addsOf(i).includes(p.add) ? `${title}　${addLabel(i, p.add)}` : title;      // 追加ページの場所は、その追加ページの名前を付ける
      }
      return placeLabel(p.page, p.ref);
    }

    // スライドの節の見出し（info.sections にある節だけ。なければ null）
    function sectionTitleOf(slide) {
      const list = Array.isArray(info.sections) ? info.sections : [];
      const sec = typeof slide.section === 'string' ? list.find(x => x && x.id === slide.section) : null;
      if (!sec) return null;
      return typeof sec.title === 'string' && sec.title ? sec.title : sec.id;
    }

    function slideTitleOf(i) {
      const t = slides[i].title;
      return typeof t === 'string' && t ? t : slides[i].id;
    }

    // 縮小1枚分の枠：1920×1080 の描画先を scale 倍に縮めて入れ、最後の段階を描く（縮小一覧と一覧つきの画面が使う）。
    // frameClass：枠の class。where：警告に書く場所の名前。描けなければ broken を true にして返す（1枚の失敗で一覧を作れなくしない）
    function buildThumbFrame(i, frameClass, scale, where) {
      const frame = el('div', frameClass);
      const target = el('div', 'sp-target');
      target.setAttribute('aria-hidden', 'true');
      target.setAttribute('inert', '');                          // 中身のリンクやボタンに焦点・クリックが届かないように
      Object.assign(target.style, {
        position: 'absolute', left: '0', top: '0', margin: '0', width: STAGE_W + 'px', height: STAGE_H + 'px',
        transformOrigin: '0 0', transform: `scale(${scale})`,
      });
      frame.appendChild(target);
      let broken = false;
      try {
        window.slideDeck.render(i, slides[i].steps, target);
      } catch (e) {
        broken = true;
        console.warn(`プレイヤー：${where}で ${slides[i].id} を描けませんでした`, e);
      }
      return { frame, broken };
    }

    function buildThumb(i) {
      const thumb = el('div', 'sp-thumb');
      thumb.dataset.index = String(i);
      thumb.setAttribute('role', 'button');
      thumb.setAttribute('aria-label', `${i + 1} / ${slides.length}　${slideTitleOf(i)}`);
      thumb.tabIndex = -1;                                       // 焦点が乗るのは選択中の1つだけ（setSelection が付け替える）
      const { frame, broken } = buildThumbFrame(i, 'sp-thumb-frame', THUMB_W / STAGE_W, '縮小一覧');
      if (broken) thumb.classList.add('sp-thumb-broken');
      const caption = el('div', 'sp-thumb-caption', `${i + 1}　${slideTitleOf(i)}`);
      caption.title = caption.textContent;
      thumb.append(frame, caption);
      thumb.addEventListener('click', () => openThumb(thumb));
      return thumb;
    }
    // 追加ページのサムネイル：白い枠に「白紙」（書き込みは入れない）
    function buildAddThumb(i, add) {
      const thumb = el('div', 'sp-thumb sp-thumb-add');
      thumb.dataset.index = String(i);
      thumb.dataset.add = add;
      thumb.setAttribute('role', 'button');
      thumb.setAttribute('aria-label', `${i + 1}${addLabel(i, add)} / ${slides.length}　白紙`);
      thumb.tabIndex = -1;
      const frame = el('div', 'sp-thumb-frame');
      frame.appendChild(el('div', 'sp-thumb-blank', '白紙'));
      thumb.append(frame, el('div', 'sp-thumb-caption', addLabel(i, add)));
      thumb.addEventListener('click', () => openThumb(thumb));
      return thumb;
    }

    // 選択を i にする（焦点もそこへ移す）。scroll：一覧の中でそのサムネイルを見える所へ動かす向き
    function setSelection(i, scroll) {
      const prev = overviewThumbs[overviewSel];
      if (prev) { prev.classList.remove('sp-selected'); prev.tabIndex = -1; }
      overviewSel = i;
      const thumb = overviewThumbs[i];
      thumb.classList.add('sp-selected');
      thumb.tabIndex = 0;
      thumb.focus({ preventScroll: true });
      thumb.scrollIntoView({ block: scroll, inline: 'nearest' });
    }

    // 矢印キーで動く先（今の位置は変えない）。← →：並びの順で1つ前・後（行の端では次・前の行へ続く）。
    // ↑ ↓：画面に出ている位置で、となりの行のうち、横の中心が一番近いもの（行がなければそのまま）
    function neighborOf(from, key) {
      if (key === 'ArrowLeft') return Math.max(from - 1, 0);
      if (key === 'ArrowRight') return Math.min(from + 1, overviewThumbs.length - 1);
      const dir = key === 'ArrowDown' ? 1 : -1;
      const rects = overviewThumbs.map(t => t.getBoundingClientRect());
      const me = rects[from];
      let rowTop = null;
      for (const r of rects) {
        const d = (r.top - me.top) * dir;
        if (d > 4 && (rowTop === null || d < (rowTop - me.top) * dir)) rowTop = r.top;
      }
      if (rowTop === null) return from;
      const center = me.left + me.width / 2;
      let best = from, bestDistance = Infinity;
      rects.forEach((r, k) => {
        if (Math.abs(r.top - rowTop) > 2) return;
        const distance = Math.abs(r.left + r.width / 2 - center);
        if (distance < bestDistance - 0.01) { best = k; bestDistance = distance; }      // 同じ距離なら左のもの
      });
      return best;
    }

    // そのスライドの段階0へ（追加ページならその追加ページへ。直近の場所に足す）
    function openThumb(thumb) {
      const i = Number(thumb.dataset.index), add = thumb.dataset.add || null;
      closeOverview();
      go(i, 0, 'jump', false, add);
    }

    // 直近の場所を選ぶ（←→ と同じ。並びは変えない）。別のページへ移れないときは、知らせて一覧を開いたままにする
    function openRecent(vid) {
      const target = places.find(vid);
      if (!target) return;
      if (goToPlace(target, MSG_PLACE_OTHER_PAGE)) closeOverview();
    }

    const ARROW_KEYS = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'];
    function overviewKey(e) {
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      if (key === 'o') { if (!e.repeat) closeOverview(); return true; }
      // Enter：選択中のスライドを開く（焦点が乗ったプレイヤーのボタンの Enter は、ここへ来ない）。
      // Space は使わない（発表中に次へのつもりで押しても、開かないように。ほかの modal と同じで、何もしない）
      if (key === 'Enter') {
        if (!e.repeat && overviewSel >= 0) openThumb(overviewThumbs[overviewSel]);
        return true;
      }
      if (!e.shiftKey && ARROW_KEYS.includes(key) && overviewSel >= 0) {
        const next = neighborOf(overviewSel, key);
        if (next !== overviewSel) setSelection(next, 'nearest');
        return true;
      }
      return false;
    }

    const overviewOverlay = { name: 'overview', modal: true, close: closeOverview, onKey: overviewKey };
    function openOverview() {
      if (overviewEl) return;
      settleMotion();
      overviewEl = el('div', 'sp-overview');
      overviewEl.setAttribute('role', 'dialog');
      overviewEl.setAttribute('aria-modal', 'true');
      overviewEl.setAttribute('aria-label', '縮小一覧');
      const panel = el('div', 'sp-overview-panel');
      panel.tabIndex = -1;
      const head = el('div', 'sp-overview-head');
      head.append(el('div', 'sp-overview-title', '縮小一覧'), makeButton('閉じる', closeOverview));
      panel.appendChild(head);

      // 直近の場所：新しい順。今の場所に印を付ける
      const snap = places.snapshot();
      if (snap.items.length) {
        panel.appendChild(el('div', 'sp-overview-label', '直近の場所（新しい順）'));
        const recent = el('div', 'sp-recent');
        recent.setAttribute('role', 'group');
        recent.setAttribute('aria-label', '直近の場所');
        for (let k = snap.items.length - 1; k >= 0; k--) {
          const p = snap.items[k];
          const item = makeButton(recentLabel(p), () => openRecent(p.vid));
          item.classList.add('sp-recent-item');
          item.dataset.vid = p.vid;
          if (k === snap.pos) { item.classList.add('sp-recent-now'); item.setAttribute('aria-current', 'true'); }
          recent.appendChild(item);
        }
        panel.appendChild(recent);
      }

      // サムネイル：続いた同じ節ごとにまとめ、節の最初の前に見出しを置く（節のないスライド・デッキは見出しなし）
      const sections = el('div', 'sp-sections');
      overviewThumbs = [];
      let grid = null, lastTitle;
      slides.forEach((slide, i) => {
        const title = sectionTitleOf(slide);
        if (!grid || title !== lastTitle) {
          if (title !== null) {
            const heading = el('div', 'sp-section-title', title);
            heading.setAttribute('role', 'heading');
            heading.setAttribute('aria-level', '2');
            sections.appendChild(heading);
          }
          grid = el('div', 'sp-grid');
          sections.appendChild(grid);
          lastTitle = title;
        }
        const thumb = buildThumb(i);
        overviewThumbs.push(thumb);
        grid.appendChild(thumb);
        for (const add of addsOf(i)) {
          const addThumb = buildAddThumb(i, add);
          overviewThumbs.push(addThumb);
          grid.appendChild(addThumb);
        }
      });
      panel.appendChild(sections);
      overviewEl.appendChild(panel);
      closeOnBackdrop(overviewEl, closeOverview);
      document.body.appendChild(overviewEl);
      overlays.push(overviewOverlay, overviewEl);                // 焦点を移す前に呼ぶ（開く前の焦点を覚える）
      buttons.overview.setAttribute('aria-pressed', 'true');
      const now = overviewThumbs.findIndex(t => Number(t.dataset.index) === cur && (t.dataset.add || null) === curAdd);
      overviewThumbs[now].classList.add('sp-current');           // 今のスライド（追加ページ）を枠で示し、最初の選択にする
      overviewThumbs[now].setAttribute('aria-current', 'true');
      setSelection(now, 'center');
    }
    function closeOverview() {
      if (!overviewEl) return;
      overviewEl.remove();                                       // サムネイルの描画先もここで全部外れる
      overviewEl = null;
      overviewThumbs = [];
      overviewSel = -1;
      overlays.remove(overviewOverlay);
      buttons.overview.setAttribute('aria-pressed', 'false');
    }
    commands.overview = () => (overviewEl ? closeOverview() : openOverview());

    // ---- リンク（約束 §2.4、§3.3）----

    const asText = v => (typeof v === 'string' ? v : '');

    // target を URL にする。許可する種類（schemes）でなければ・読めなければ null。base がなければ、絶対 URL だけ読む
    function linkUrl(target, schemes, base) {
      if (!target) return null;
      try {
        const u = base ? new URL(target, base) : new URL(target);
        return schemes.includes(u.protocol) ? u : null;
      } catch (e) { return null; }
    }

    // リンク1件を調べる。使えるもの：{kind, ...}。動かせないもの：{kind: "broken", reason: "id"|"url"|"text", shown}
    // （ないスライドの ID、許可しない種類の URL、写す文字のない copy）。種類を知らないもの・形が違うものは null（印も動きもない）
    function resolveLink(link) {
      if (!link || typeof link !== 'object') return null;
      switch (link.kind) {
        case 'jump': {
          const target = asText(link.target);
          const m = LINK_ID_RE.exec(target);
          if (m) {                                               // 同じデッキの中。ない ID は壊れたリンク
            const i = indexOf(m[1]);
            if (i < 0) return { kind: 'broken', reason: 'id', shown: target };
            return { kind: 'jump', index: i, step: m[2] === undefined ? 0 : Math.min(parseInt(m[2], 10), slides[i].steps) };
          }
          const url = linkUrl(target, LINK_PAGE_SCHEMES, location.href);     // このページからの相対 URL として、別のページへ
          return url ? { kind: 'jump', url } : { kind: 'broken', reason: 'url', shown: target };
        }
        case 'external': {
          const target = asText(link.target);
          const url = linkUrl(target, LINK_EXTERNAL_SCHEMES);
          return url ? { kind: 'external', url } : { kind: 'broken', reason: 'url', shown: target };
        }
        case 'more': return { kind: 'more', title: asText(link.title) || asText(link.label), text: asText(link.text) };
        case 'copy': return asText(link.text) ? { kind: 'copy', text: link.text } : { kind: 'broken', reason: 'text', shown: asText(link.label) };
        default: return null;
      }
    }

    // 描いた要素の data-link の番号。そのスライドの links の範囲の外・整数でないときは -1
    function spotNumber(node) {
      const links = slides[cur].links;
      const text = node.getAttribute('data-link');
      return Array.isArray(links) && /^(0|[1-9]\d*)$/.test(text) && Number(text) < links.length ? Number(text) : -1;
    }
    const infoOfSpot = node => {
      const n = spotNumber(node);
      return n < 0 ? null : resolveLink(slides[cur].links[n]);
    };

    // 描いたあとで、舞台の data-link の要素に data-sp-kind（jump・external・more・copy・broken）を付ける（印は CSS）。
    // 範囲の外の番号の要素には何も付けない。焦点を受けられるように tabindex を付ける（Enter で開く）
    function markLinks() {
      for (const node of stage.querySelectorAll('[data-link]')) {
        const info = infoOfSpot(node);
        if (!info) { node.removeAttribute('data-sp-kind'); continue; }
        node.setAttribute('data-sp-kind', info.kind);
        if (!node.hasAttribute('tabindex')) node.tabIndex = 0;
        if (!node.hasAttribute('role')) node.setAttribute('role', info.kind === 'more' || info.kind === 'copy' ? 'button' : 'link');
      }
    }

    // 印の文字（→ ↗ ＋ ⧉ ⚠）を、見えているリンクの要素ごとに、舞台の外の層に置く。層は画面に固定で、舞台の中身には何も足さない
    // （舞台の中に ::after などで足すと、幅・行の高さ・折り返しが変わるため。約束 §3.2・§2.5）。
    // 文字の中のリンク（inline）は、最後の行の右端の上（肩つき。つづく文字をほとんど覆わない）、箱のリンクは、箱の右上の内側に置く。文字の大きさは、要素の文字の大きさに合わせる。
    // 描き直し（go）・画面の大きさやノートの開閉（fitStage）・字体の読み込みのあとで置き直す
    function layoutLinkMarks() {
      if (!markLayer) {
        markLayer = el('div', 'sp-linkmarks');
        markLayer.setAttribute('aria-hidden', 'true');
        document.body.appendChild(markLayer);
      }
      markLayer.textContent = '';
      if (curAdd !== null) return;                               // 追加ページにはリンクの印を出さない
      const k = stageScale, area = centerArea(), areaRight = area.left + area.width;     // 印は中央の領域の右端の内側に収める
      for (const node of stage.querySelectorAll('[data-sp-kind]')) {
        if (!isSpotVisible(node)) continue;
        const rects = node.getClientRects();
        const r = rects[rects.length - 1];
        const style = window.getComputedStyle(node);
        const kind = node.getAttribute('data-sp-kind');
        const size = Math.max(parseFloat(style.fontSize) * .55, 22) * k;
        const outside = style.display === 'inline';
        const mark = el('span', 'sp-linkmark', LINK_MARKS[kind]);
        mark.dataset.kind = kind;
        mark.dataset.index = node.getAttribute('data-link');
        mark.style.fontSize = size + 'px';
        if (kind !== 'broken') mark.style.color = style.color;
        mark.style.left = Math.min(outside ? r.right - size * .15 : r.right - size - 4 * k, areaRight - size) + 'px';
        mark.style.top = (outside ? r.top - size * .75 : r.top + 4 * k) + 'px';
        markLayer.appendChild(mark);
      }
    }

    // 見えているか。visibility: hidden（自分か祖先）や display: none のものは押せず、L にも出さない（約束 §2.4）
    const isSpotVisible = node => node.getClientRects().length > 0 && window.getComputedStyle(node).visibility === 'visible';

    // 出来事の相手から、舞台の中の data-link の要素（一番内側）を探す
    function spotOf(target) {
      if (curAdd !== null) return null;                          // 追加ページには押せるリンクがない
      const start = target && target.nodeType === 1 ? target : target && target.parentElement;
      const node = start ? start.closest('[data-link]') : null;
      return node && stage.contains(node) ? node : null;
    }

    // 舞台の要素を押した・Enter を押した。リンクが使えて、見えているときだけ動く（動いたら true）
    function activateSpot(node) {
      const info = infoOfSpot(node);
      if (!info || !isSpotVisible(node)) return false;
      runLink(info);
      return true;
    }

    // リンクを開く。別のページへは openPage を通る（残っている復元先を消してから移る）
    function runLink(info) {
      switch (info.kind) {
        case 'jump':
          if (info.url) openPage(info.url.href);
          else go(info.index, info.step, 'jump');
          break;
        case 'external':
          try { window.open(info.url.href, '_blank', 'noopener'); } catch (e) { toast(MSG_LINK_BLOCKED); }
          break;
        case 'more':
          openMore(info.title, info.text);
          break;
        case 'copy':
          copyText(info.text);
          break;
        default:
          toast(info.reason === 'id' ? MSG_LINK_NO_SLIDE(info.shown) : info.reason === 'text' ? MSG_LINK_NO_TEXT : MSG_LINK_BLOCKED);
      }
    }

    // コピー：写せたら知らせる。使えない・断られたときは、成功と知らせず、文字を選んだ状態で見せる（約束 §2.4）
    function copyText(text) {
      const fail = () => openMore(MSG_COPY_FAILED, text, { hint: MSG_COPY_BY_HAND, select: true });
      let done;
      try { done = navigator.clipboard.writeText(text); } catch (e) { fail(); return; }
      Promise.resolve(done).then(() => toast(MSG_COPIED), fail);
    }

    // ---- 補足の窓（more）----

    // 補足の窓 .sp-more：題（.sp-more-title）と文字（.sp-more-text）。modal で、Esc・閉じる・背景で閉じる。
    // opts.hint：文字の下に出す案内。opts.select：文字を選んだ状態にする（コピーできなかったとき）
    const moreOverlay = { name: 'more', modal: true, close: closeMore };
    function openMore(title, text, opts) {
      settleMotion();
      if (moreEl) closeMore();
      const { hint = '', select = false } = opts || {};
      moreEl = el('div', 'sp-more');
      moreEl.setAttribute('role', 'dialog');
      moreEl.setAttribute('aria-modal', 'true');
      moreEl.setAttribute('aria-label', title || '補足');
      const panel = el('div', 'sp-more-panel');
      panel.tabIndex = -1;
      if (title) panel.appendChild(el('div', 'sp-more-title', title));
      const body = el('div', select ? 'sp-more-text sp-more-copy' : 'sp-more-text', text);
      panel.appendChild(body);
      if (hint) panel.appendChild(el('div', 'sp-more-hint', hint));
      const closeRow = el('div', 'sp-more-close');
      closeRow.appendChild(makeButton('閉じる', closeMore));
      panel.appendChild(closeRow);
      moreEl.appendChild(panel);
      closeOnBackdrop(moreEl, closeMore);
      document.body.appendChild(moreEl);
      overlays.push(moreOverlay, moreEl);                        // 焦点を移す前に呼ぶ（開く前の焦点を覚える）
      panel.focus({ preventScroll: true });
      if (select) {                                              // 焦点を移したあとで選ぶ（手でコピーできるように）
        try {
          const range = document.createRange();
          range.selectNodeContents(body);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
        } catch (e) { /* 選べなくても、文字は見える */ }
      }
    }
    function closeMore() {
      if (!moreEl) return;
      moreEl.remove();
      moreEl = null;
      overlays.remove(moreOverlay);
    }

    // ---- リンクを表示（L）----

    // リンクを表示 .sp-linkview：画面を少し暗くし、見えているリンクの要素ごとに枠 .sp-linkframe（ボタン。押すとそのリンクを開く、data-index はリンクの番号）、
    // その中に移動先の札 .sp-linktag を出す。場所のない（舞台に data-link の要素がない）リンクは、隅の一覧 .sp-linklist-item（押せる）。
    // 段階で隠れた要素のリンクは出さない。modal：L・Esc で閉じる。開いている間にスライドが変われば閉じる（go）
    const FRAME_PAD = 5;                                         // 枠を要素より広げる分（px）
    const LABEL_MAX = 80;                                        // 札と一覧に出す文字の長さ（これを超えたら省く）
    const shorten = s => { const flat = s.replace(/\s+/g, ' '); return flat.length > LABEL_MAX ? flat.slice(0, LABEL_MAX) + '…' : flat; };

    // 移動先の札の文字。同じデッキ：スライドの題名（段階があれば付ける）、別のページ：「ページ名：ID」（placeLabel）、外部：URL、補足：題、コピー：「コピー：文字」、
    // 壊れたもの：「見つからない：ID」（ほかは「開けない：…」）
    function destText(info) {
      switch (info.kind) {
        case 'jump': return info.url ? urlLabel(info.url) : slideTitleOf(info.index) + (info.step > 0 ? `（段階 ${info.step}）` : '');
        case 'external': return shorten(info.url.href);
        case 'more': return info.title || '補足';
        case 'copy': return 'コピー：' + shorten(info.text);
        default: return `${info.reason === 'id' ? '見つからない' : '開けない'}：${shorten(info.shown)}`;
      }
    }

    // 今のスライドのリンクを、舞台に見えている要素のあるもの（spots、文書の順）と、舞台に要素がないもの（placeless）に分ける。
    // 要素はあるが隠れているだけのリンクは、どちらにも入れない
    function collectLinks() {
      if (curAdd !== null) return { spots: [], placeless: [] };      // 追加ページは「リンクがない」
      const links = Array.isArray(slides[cur].links) ? slides[cur].links : [];
      const infos = links.map(resolveLink);
      const labelOf = n => asText(links[n].label);
      const spots = [], placed = new Set();
      for (const node of stage.querySelectorAll('[data-link]')) {
        const n = spotNumber(node);
        if (n < 0 || !infos[n]) continue;
        placed.add(n);
        if (isSpotVisible(node)) spots.push({ n, node, info: infos[n], label: labelOf(n) });
      }
      const placeless = [];
      infos.forEach((info, n) => { if (info && !placed.has(n)) placeless.push({ n, info, label: labelOf(n) }); });
      return { spots, placeless };
    }

    // 枠を要素の位置に置き、札の置き方（下・上、左そろえ・右そろえ）を決める。画面の中に収まり、ほかの枠・札と重ならない置き方を先に選ぶ
    // （どれもだめなら、画面の中に収まるものを、それもなければ下・左そろえ）。画面は中央の領域（左の列とノートを除いた所）で、隅の一覧もその右上に置く
    const TAG_PLACEMENTS = [[], ['sp-above'], ['sp-right'], ['sp-above', 'sp-right']];
    const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
    // 札が中央の領域から左右にはみ出すときの、横のずらし量（領域より広いときは、画面の中・左右 8px に収める）
    function tagShift(t, areaLeft, areaRight, vw) {
      let [lo, hi] = [areaLeft, areaRight];
      if (t.width > hi - lo) [lo, hi] = [8, vw - 8];
      return t.left < lo ? lo - t.left : t.right > hi ? hi - t.right : 0;
    }
    function layoutLinkView() {
      if (!linkViewEl) return;
      const area = centerArea(), vh = window.innerHeight;
      const areaLeft = area.left, areaRight = area.left + area.width;
      linkPanelEl.style.right = window.innerWidth - areaRight + 16 + 'px';      // 隅の一覧は、中央の領域の右上
      linkPanelEl.style.maxWidth = Math.max(1, Math.min(420, area.width - 32)) + 'px';
      for (const { frame, node } of linkFrames) {
        const r = node.getBoundingClientRect();
        Object.assign(frame.style, {
          left: r.left - FRAME_PAD + 'px', top: r.top - FRAME_PAD + 'px',
          width: r.width + FRAME_PAD * 2 + 'px', height: r.height + FRAME_PAD * 2 + 'px',
        });
      }
      const frameRects = linkFrames.map(f => f.frame.getBoundingClientRect());
      const panelRect = linkPanelEl.getBoundingClientRect();
      const taken = [panelRect];                                 // すでに置いた札と、一覧
      const vw = window.innerWidth;
      const tagMax = Math.min(420, vw - 16, Math.max(160, area.width - 16)) + 'px';
      linkFrames.forEach(({ frame, tag }, i) => {
        let best = null;
        tag.style.maxWidth = tagMax;
        // 横にずらしたあとの矩形で、収まりと重なりを決める（ずらしたせいでほかの枠に重ならないように）
        for (const classes of TAG_PLACEMENTS) {
          frame.classList.remove('sp-above', 'sp-right');
          frame.classList.add(...classes);
          tag.style.transform = '';                              // 前の配置のずれを測り値に残さない
          const m = tag.getBoundingClientRect();
          const dx = tagShift(m, areaLeft, areaRight, vw);
          const t = { left: m.left + dx, right: m.right + dx, top: m.top, bottom: m.bottom };
          const inside = t.left >= areaLeft && t.top >= 0 && t.right <= areaRight && t.bottom <= vh;
          const clear = !taken.some(o => overlaps(t, o)) && !frameRects.some((o, k) => k !== i && overlaps(t, o));
          const cost = (inside ? 0 : 2) + (clear ? 0 : 1);
          if (!best || cost < best.cost) best = { classes, cost, rect: t, dx };
          if (cost === 0) break;
        }
        frame.classList.remove('sp-above', 'sp-right');
        frame.classList.add(...best.classes);
        tag.style.transform = best.dx ? `translateX(${best.dx}px)` : '';
        taken.push(best.rect);
      });
    }

    function followFromView(info) {
      closeLinkView();                                           // 先に閉じる（焦点を戻してから、補足の窓などを開く）
      runLink(info);
    }

    function linkViewKey(e) {
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      if (key === 'l') { if (!e.repeat) closeLinkView(); return true; }
      return false;
    }

    const linkViewOverlay = { name: 'links', modal: true, close: closeLinkView, onKey: linkViewKey };
    function openLinkView() {
      if (linkViewEl) return;
      settleMotion();                                            // 描画待ちがあると、古い舞台の要素と新しいスライドの links を組み合わせてしまう
      const { spots, placeless } = collectLinks();
      if (!spots.length && !placeless.length) { toast(MSG_LINK_NONE); return; }
      linkViewEl = el('div', 'sp-linkview');
      linkViewEl.tabIndex = -1;
      linkViewEl.setAttribute('role', 'dialog');
      linkViewEl.setAttribute('aria-modal', 'true');
      linkViewEl.setAttribute('aria-label', 'リンクを表示');

      // 隅の一覧：閉じるボタンと、場所のないリンク
      const panel = linkPanelEl = el('div', 'sp-linkpanel');
      const head = el('div', 'sp-linkpanel-head');
      head.append(el('span', '', 'リンク'), makeButton('閉じる', closeLinkView));
      panel.appendChild(head);
      if (placeless.length) {
        const list = el('div', 'sp-linklist');
        list.appendChild(el('div', 'sp-linklist-title', 'スライドに場所のないリンク'));
        for (const { info, label } of placeless) {
          const item = makeButton('', () => followFromView(info));
          item.classList.add('sp-linklist-item');
          item.dataset.kind = info.kind;
          item.append(el('span', 'sp-linklist-label', shorten(label)), el('span', 'sp-linklist-dest', destText(info)));
          list.appendChild(item);
        }
        panel.appendChild(list);
      }
      linkViewEl.appendChild(panel);

      // 枠と札：舞台の要素ごと
      linkFrames = spots.map(({ n, node, info, label }) => {
        const dest = destText(info);
        const frame = makeButton('', () => followFromView(info));
        frame.classList.add('sp-linkframe');
        frame.dataset.index = String(n);
        frame.dataset.kind = info.kind;
        frame.setAttribute('aria-label', label ? `${shorten(label)}：${dest}` : dest);
        const tag = el('span', 'sp-linktag', dest);
        frame.appendChild(tag);
        linkViewEl.appendChild(frame);
        return { frame, tag, node };
      });

      closeOnBackdrop(linkViewEl, closeLinkView);
      document.body.appendChild(linkViewEl);
      overlays.push(linkViewOverlay, linkViewEl);                // 焦点を移す前に呼ぶ（開く前の焦点を覚える）
      buttons.links.setAttribute('aria-pressed', 'true');
      layoutLinkView();
      linkViewEl.focus({ preventScroll: true });
    }
    function closeLinkView() {
      if (!linkViewEl) return;
      linkViewEl.remove();
      linkViewEl = linkPanelEl = null;
      linkFrames = [];
      overlays.remove(linkViewOverlay);
      buttons.links.setAttribute('aria-pressed', 'false');
    }
    commands.links = () => (linkViewEl ? closeLinkView() : openLinkView());

    // 中身の中のふつうの <a href="#…">（data-link でない同じ文書の hash）。スライドの hash として読めないもの（#foo、# だけ）は、
    // ブラウザに任せると、読めない hash への変更で先頭のスライドに戻る（# だけならページの先頭へ動く）ので、止める。
    // 読めるもの（#s05）は止めず、今までどおりブラウザの hash の変更として移る
    function plainHashAnchor(target) {
      const start = target && target.nodeType === 1 ? target : target && target.parentElement;
      const a = start ? start.closest('a[href^="#"]') : null;
      return a && stage.contains(a) ? a : null;
    }

    // 舞台のリンクを押した（舞台に付ける listener は1つ）。縮小一覧のサムネイルは別の描画先で、ここへは届かない。
    // プレイヤーがリンクとして扱ったクリックは preventDefault する（中身が <a href> を data-link に使っても、二重に移らない）。
    // Ctrl・Cmd・Shift・Alt を押したクリックと、主ボタン以外（中ボタンは auxclick で、ここへは来ない）は扱わず、ブラウザの既定の動き
    // （新しいタブ・窓で開く、保存する、など）に任せる
    stage.addEventListener('click', e => {
      if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      // 描画待ちの間に届いたクリックは、移る前のスライドへの操作。最新の舞台を描いたうえで、リンクとしても、ブラウザの既定の動き
      // （<a href> の移動）としても扱わない。DOM に要素が残っているかでは決めない：始まったクリックの既定の動きは、要素を外しても止まらず、
      // 描画関数が同じリンクの要素を使い回すと、古いクリックが移動先の同じ番号のリンクに読み替えられる
      if (writing.active()) { e.preventDefault(); return; }         // 書き込みの間は、舞台のリンクを開かない（Enter で起きるクリックも）
      if (unpainted || entries.active()) { settleMotion(); e.preventDefault(); return; }   // 入場の途中は、まだ見えていない要素を押させない
      const node = spotOf(e.target);
      if (node && activateSpot(node)) { e.preventDefault(); return; }
      const anchor = plainHashAnchor(e.target);
      if (anchor && view.read(anchor.getAttribute('href')).kind !== 'ok') e.preventDefault();
    });

    // ---- Esc ----

    // Esc：一番上の重なりを閉じる。重なりがなければ、開いているノートを閉じる。何も開いていなければ何もしない（false）
    function closeTopmost() {
      if (writing.escape()) return true;                         // 書き込みの中の段階（文字の欄 → 選ぶ → 窓を閉じる・ロックを外す）が先
      const top = overlays.top();
      if (top) { top.close(); return true; }
      if (writing.active()) { writing.stop(); return true; }     // 重なりの次は書き込みを終える
      if (notesEl) { setNotes(false, true); return true; }
      return false;
    }

    // ---- キー操作 ----

    // ↓・↑：次の段階 → 次のスライドの段階0、前の段階 → 前のスライドの最後の段階
    // 追加ページは段階のない1ページ：スライドの最後の段階の次が追加ページ（並びの順）、その次が次のスライド
    function moveInOrder(dir) {
      if (dir > 0) {
        if (curAdd === null && curStep < slides[cur].steps) { go(cur, curStep + 1, 'order'); return; }
        const next = nextPage();
        if (next) go(next.index, next.step, 'order', next.add === null && next.index !== cur, next.add);
        else toast(MSG_LAST);
      } else {
        if (curAdd === null && curStep > 0) { go(cur, curStep - 1, 'order'); return; }
        const prev = prevPage();
        if (prev) go(prev.index, prev.step, 'order', false, prev.add);
        else toast(MSG_FIRST);
      }
    }

    // Shift＋↓：次のスライドの段階0。Shift＋↑：前のスライドの最後の段階
    // 追加ページも1ページとして通る（段階は飛ばす）
    function moveBySlide(dir) {
      const next = dir > 0 ? nextPage() : prevPage();
      if (!next) { toast(dir > 0 ? MSG_LAST : MSG_FIRST); return; }
      if (dir > 0) go(next.index, next.add === null ? 0 : next.step, 'jump', next.add === null, next.add);
      else go(next.index, next.step, 'jump', false, next.add);
    }

    // Home・End：最初・最後のスライドの段階0
    function moveToEdge(index) {
      if (cur === index && curStep === 0 && curAdd === null) toast(index === 0 ? MSG_FIRST : MSG_LAST);
      else go(index, 0, 'jump');
    }

    // キーに対する動き（なければ null）。Shift は ↑↓ だけが使う
    function actionFor(e) {
      const shift = e.shiftKey;
      switch (e.key) {
        case 'ArrowDown': return () => (shift ? moveBySlide(1) : moveInOrder(1));
        case 'ArrowUp': return () => (shift ? moveBySlide(-1) : moveInOrder(-1));
        case 'PageDown': case ' ': return shift ? null : () => moveInOrder(1);
        case 'PageUp': return shift ? null : () => moveInOrder(-1);
        case 'Home': return shift ? null : () => moveToEdge(0);
        case 'End': return shift ? null : () => moveToEdge(slides.length - 1);
        case 'ArrowLeft': return shift ? null : () => movePlace(-1);
        case 'ArrowRight': return shift ? null : () => movePlace(1, () => moveInOrder(1));
        default: return null;
      }
    }

    // ---- PDF の書き出し（P）----
    // 印刷の回：入れ物は1つだけ（作ってあれば使い回す）。元の題名はその回で最初に作ったときだけ覚える。
    // 片付け（endPrint）は afterprint・時間切れ・例外のときだけ（window.print() から戻っただけでは消さない。何度呼んでも安全）。
    // ⌘P は beforeprint で同期に作るだけ（待てない）。P は字体と画像を待ってから window.print() を呼ぶ
    let printBox = null;                                         // 印刷用の入れ物（なければ null）
    let printTitle = null;                                       // 印刷の前の document.title（この回で覚えていなければ null）
    let printBusy = false;                                       // P の準備中・印刷中（afterprint か片付けまで）

    function buildPrint() {
      writing.commitText();                                      // 入力中の文字は先に確定する（PDF に入れる）
      if (printBox) return;
      const box = el('div', 'sp-print');
      box.setAttribute('aria-hidden', 'true');
      box.setAttribute('inert', '');
      document.body.appendChild(box);                            // 配置された状態で描く（字体や画像の読み込みも始まる）
      printBox = box;
      for (const { index: i, add } of pageSeq()) {              // デッキの順（元のスライドと、その直後の追加ページ）。P も ⌘P もここを通る
        const slide = slides[i];
        const page = el('div', 'sp-print-page');
        box.appendChild(page);
        if (add) page.classList.add('sp-print-blank');           // 追加ページは白いページ（render を呼ばない）
        else {
          const target = el('div', 'sp-target');
          target.setAttribute('aria-hidden', 'true');
          target.setAttribute('inert', '');
          page.appendChild(target);
          try {
            window.slideDeck.render(i, slide.steps, target);
          } catch (e) {
            const name = typeof slide.id === 'string' && slide.id ? slide.id : `${i + 1}枚目`;
            console.warn(`プレイヤー：PDF で ${name} を描けませんでした`, e);
            target.textContent = '';
            target.appendChild(el('div', 'sp-render-error', MSG_RENDER_FAILED(name)));
          }
        }
        const key = add ? 'a:' + add : 's:' + String(slide.id);
        if (writing.count(key) > 0) {                            // 書き込みのあるページだけ、舞台の座標のまま同じ大きさで重ねる（同期に描く）
          const ink = el('canvas', 'sp-print-ink');
          ink.width = STAGE_W;
          ink.height = STAGE_H;
          page.appendChild(ink);
          const c = ink.getContext('2d');
          if (c) writing.paint(c, key);
        }
      }
      if (printTitle === null) printTitle = document.title;     // ファイル名の候補にする題名（label title）
      const title = typeof info.title === 'string' && info.title ? info.title : printTitle;
      document.title = typeof info.label === 'string' && info.label ? `${info.label} ${title}` : title;
    }

    function endPrint() {
      if (printBox) { printBox.remove(); printBox = null; }
      if (printTitle !== null) { document.title = printTitle; printTitle = null; }
      printBusy = false;
    }

    // 入れ物の字体と画像の読み込みを待つ。画像は decode() の失敗も待ち終わり（壊れたまま写る）。上限を過ぎたら false
    function waitPrintReady(box) {
      const jobs = [];
      try { if (document.fonts && document.fonts.ready) jobs.push(Promise.resolve(document.fonts.ready).catch(() => {})); } catch (e) { /* 字体を待てなくても続ける */ }
      for (const img of box.querySelectorAll('img')) {
        try { jobs.push(Promise.resolve(img.decode()).catch(() => {})); } catch (e) { /* decode がなくても続ける */ }
      }
      return new Promise(resolve => {
        const timer = setTimeout(() => resolve(false), PRINT_WAIT_MS);
        Promise.all(jobs).then(() => { clearTimeout(timer); resolve(true); });
      });
    }

    function printDeck() {
      if (printBusy) return;                                     // 準備中・印刷中の P は受けない
      printBusy = true;
      try {
        settleMotion();
        buildPrint();
      } catch (e) {
        console.warn('プレイヤー：PDF の準備に失敗しました', e);
        endPrint();
        toast(MSG_PRINT_FAILED);
        return;
      }
      const box = printBox;
      waitPrintReady(box).then(ready => {
        if (printBox !== box) return;                            // 待っている間に片付いた古い回。今の回の状態（printBusy・入れ物・題名）には触れない
        if (!ready) { endPrint(); toast(MSG_PRINT_TIMEOUT); return; }
        try {
          window.print();                                        // 戻っても消さない（afterprint で消す）
          printBusy = false;                                     // 戻ったら次の P を受ける（afterprint が来ない環境でも P が効く。入れ物は afterprint まで残す）
        } catch (e) {
          console.warn('プレイヤー：window.print() に失敗しました', e);
          endPrint();
          toast(MSG_PRINT_FAILED);
        }
      });
    }
    window.addEventListener('beforeprint', () => { try { buildPrint(); } catch (e) { console.warn('プレイヤー：印刷用の表示を作れませんでした', e); endPrint(); } });
    window.addEventListener('afterprint', endPrint);

    // 離れる前の確認：書き込みか追加ページがあるときだけ。「留まる」を知る手段がないので、
    // 0.3 秒後も見えていれば（確認の窓が出ている間は時計が止まる）留まったとして知らせる
    window.addEventListener('beforeunload', e => {
      writing.commitText();                                      // 入力中の文字を先に確定する（空なら何も残らない）
      if (!writing.hasAny() && !adds.size) return;
      e.preventDefault();
      e.returnValue = '';
      setTimeout(() => { if (document.visibilityState === 'visible') toast(MSG_STAY_WRITING); }, 300);
    });

    // ? N M T F は重なりが開いていても効く。H O L は重なりが（modal で）開いているときは効かない
    function toggleFor(key) {
      switch (key) {
        case '?': return toggleHelp;
        case 'n': return toggleNotes;
        case 'm': return toggleMemo;
        case 't': return toggleSide;
        case 'f': return toggleFullscreen;
        default: return null;
      }
    }
    function commandFor(key) {
      switch (key) {
        case 'h': return homeUrl ? goHome : null;
        case 'o': return commands.overview;
        case 'l': return commands.links;
        case 'p': return printDeck;
        case 'd': return writing.toggle;
        case 'e': return writing.active() ? writing.clear : null;  // E は書き込みの間だけ（今のページの書き込みを全部消す。ひとつ戻すで戻せる）
        default: return null;
      }
    }

    // Enter でブラウザが自分でクリックを起こす要素（href のある a・area、button、input、select、textarea、summary）は、クリックの listener に任せる（二重にしない）。
    // href のない a は、ブラウザは Enter で何もしない。span と同じく、プレイヤーが Enter で1回だけ開く
    const NATIVE_ACTIVATION = 'a[href], area[href], button, input, select, textarea, summary';
    document.addEventListener('keydown', e => {
      // ⌘Z・Ctrl＋Z：書き込みの間で、文字の入力欄の外にいるときだけ、ひとつ戻す（入力欄の中はブラウザーの取り消しのまま）。修飾キーの早期 return より前で受ける
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && !e.isComposing && !e.defaultPrevented && e.key.toLowerCase() === 'z'
        && writing.active() && !isTyping(e.target) && !modalOpen()) { e.preventDefault(); writing.undo(); return; }
      if (e.defaultPrevented || ignoredKey(e)) return;           // すでにほかが扱ったキー・修飾キー付き・入力中は扱わない
      // 焦点が乗ったプレイヤーのボタンの Space・Enter は、そのボタンを押す動作（ブラウザに任せる）。
      // ただし、操作ボタンをキーボードで押したあと（焦点が帯に残っている間）の Space は、押し直さず、移動として扱う
      if (isOwnButton(e.target) && (e.key === 'Enter' || (e.key === ' ' && e.target !== pressedByKey))) return;
      const top = overlays.top();
      if (top && top.onKey && top.onKey(e)) { e.preventDefault(); return; }    // 一番上の重なりが先に受ける
      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;           // CapsLock・Shift の大文字も同じキーとして扱う
      if (key === 'Escape') { if (closeTopmost()) e.preventDefault(); return; }
      if ((key === 'Delete' || key === 'Backspace') && writing.active() && writing.hasSelection() && !isTyping(e.target) && !modalOpen()) { e.preventDefault(); writing.removeSelected(); return; }
      const toggle = toggleFor(key);
      if (toggle) { e.preventDefault(); if (!e.repeat) toggle(); return; }
      if (top && top.modal) {                                    // modal の重なりの間は、ここから下（移動・H O L）は動かさない
        if (key === 'Tab') { e.preventDefault(); overlays.trapTab(top, e); }     // Tab は重なりの中だけを巡る
        return;
      }
      if (key === 'Tab') {                                       // キーボードだけで使う人のために、Tab で操作ボタンを出す
        if (unpainted || entries.active()) settleMotion();        // 入場の途中なら先に確定する（まだ見えない要素に焦点が入らない）
        showControls();
        return;
      }
      if (key === 'Enter') {                                     // 焦点が乗った舞台のリンクを開く（Space は今までどおり次へ）
        // クリックと同じ：舞台の中で受けた Enter が描画待ちの間のものなら、確定して終える（a[href] などブラウザが Enter で起こすクリックも止める）。
        // 舞台の外（プレイヤーのボタン・body）の Enter は対象外。舞台の中かは、settle の前に調べる
        if (writing.active() && stage.contains(e.target)) { e.preventDefault(); return; }   // 書き込みの間は、舞台のリンクを開かない
        if ((unpainted || entries.active()) && stage.contains(e.target)) { settleMotion(); e.preventDefault(); return; }
        const node = spotOf(e.target);
        if (node && !node.matches(NATIVE_ACTIVATION)) { e.preventDefault(); if (!e.repeat) activateSpot(node); return; }
      }
      const command = commandFor(key);
      if (command) { e.preventDefault(); if (!e.repeat) command(); return; }
      const action = actionFor(e);
      if (!action) return;
      e.preventDefault();                                        // Space・PageDown などでページが動かないように
      if (controls.contains(e.target)) e.target.blur();          // 帯に焦点が残っていたら外してから動く（帯が隠れなくなる・Space が押し直しにならない）
      action();
    });
    window.addEventListener('resize', applySide);                // 幅が変わったら、列を出せるか決め直す（舞台も置き直す。設定は書かない）
    window.addEventListener('load', layoutLinkMarks);            // 字体・画像の読み込みで文字の位置が動いたら、印を置き直す
    try {
      document.fonts.ready.then(layoutLinkMarks);
      document.fonts.addEventListener('loadingdone', layoutLinkMarks);
    } catch (e) { /* 字体の読み込みを見られなくても、go と fitStage で置く */ }
    listenArrivals();
    try {
      window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', e => { if (e.matches) settleEntry(); pointer.refresh(); });
    } catch (e) { /* 見られなくても、次の移動で入場は確定する */ }

    // 試験用の窓口（通常の表示のときだけ）。overlay は、ノート以外で一番上の重なりの名前
    window.__sp = {
      state: () => ({ kind: 'deck', index: cur, step: curStep, id: slides[cur].id, add: curAdd, label: positionText() }),
      pages: () => pageSeq().map(p => ({ ...p })),
      places: () => places.snapshot(),
      overlay: () => overlays.name(),
      motion: () => ({ kind: lastMotion.kind, arrival: arrival.played }),
      motionDone: () => Promise.all([lastMotion.done, arrival.done]).then(() => {}),
      deckMotion: () => ({ ...deckMotion }),
      entry: () => entries.info(),
      memo: () => ({ band: !!memoEl, ownOpen, shared: memoStore.get(slides[cur].id, 'shared'), own: memoStore.get(slides[cur].id, 'own') }),
      writing: () => writing.state(),
      pointer: () => ({ point: stage.classList.contains('sp-point'), still: stage.classList.contains('sp-still'), light: pointer.lightActive() }),
      entryDone: () => entries.done(),
      parseHash, formatHash, openPage,
    };

    pointer.refresh();                                           // 指す層の class を付ける（デッキが選んだときだけ）
    applyControls(false);                                        // 読み込み直後は、auto なら隠す
    setNotes(settings.get().notes, false);                       // 前に開いていたら開く（保存し直さない）
    applySide();                                                 // 前に出していて、広さが足りれば出す（保存し直さない）。舞台もここで置く
    arrive();
    arrival = playArrival(stage, deckMotion.send);               // 別のページから移ってきたときだけ、舞台をフェードインさせる（送りなしのデッキは動かさない）

    // ---- Editor の口（window.slideEditor があるページだけ。ないページは何も足さない）----
    // 保存のたびに、ページを読み直さずデッキを差し替える。今のスライド・段階・書き込み・追加ページは、スライドの ID についていく。
    // 差し替えでは、切り替えの動き・入場の動きを出さず、直近の場所（places）に項目を足さず、履歴も増やさない（hash を書き換えるだけ）
    const place = () => ({ id: slides[cur].id, step: curStep, add: curAdd });
    function replaceDeck(deck) {
      const next = deck && deck.info && deck.info.slides;
      if (!deck || typeof deck.render !== 'function' || !Array.isArray(next) || !next.length) {
        console.warn('プレイヤー：差し替えるデッキ（info.slides と render）が読めないので、今のデッキのままにします');
        return { id: slides[cur].id, step: curStep };
      }
      settleMotion();                                            // 動き・入場の途中なら先に終える（描画待ちも描く）
      goSeq++;                                                   // 待っている入場の再生は取り消す
      commitMemo();                                              // 書きかけのメモは、元のスライドへ保存する
      writing.cut();
      if (linkViewEl) closeLinkView();                           // そのスライドのリンクの表示は、古いデッキのもの
      if (moreEl) closeMore();
      const reopenOverview = !!overviewEl;
      if (overviewEl) closeOverview();                           // 縮小一覧は、あとで新しいデッキで開き直す
      // ID → 追加ページの識別子の並び（番号は差し替えで変わる）
      const addsById = new Map();
      adds.forEach((list, i) => { if (!addsById.has(slides[i].id)) addsById.set(slides[i].id, list); });
      const was = { id: slides[cur].id, index: cur, step: curStep, add: curAdd };
      window.slideDeck = deck;
      slides.splice(0, slides.length, ...normalizeSlides(next));
      adds.clear();
      const kept = new Set();
      slides.forEach((s, i) => {
        if (addsById.has(s.id) && !kept.has(s.id)) { adds.set(i, addsById.get(s.id)); kept.add(s.id); }
      });
      addsById.forEach((list, id) => { if (!kept.has(id)) for (const add of list) writing.drop('a:' + add); });   // 元が消えた追加ページは、書いたものごと消す
      // 着く場所：同じ ID があればそのスライド（段階は新しい steps に縮める）。なければ同じ位置（なければ最後）の段階 0
      let index = indexOf(was.id), step, add = null;
      if (index >= 0) {
        add = was.add !== null && addsOf(index).includes(was.add) ? was.add : null;
        step = add !== null ? slides[index].steps : Math.min(was.step, slides[index].steps);
      } else {
        index = Math.min(was.index, slides.length - 1);
        step = 0;
      }
      cur = index;
      curStep = step;
      curAdd = add;
      entering = null;
      unpainted = true;                                          // 描いた印を外して、今の paintStage で描き直す（リンクの印・書き込みの層もここで付く）
      paintStage();
      lastMotion = { kind: 'none', done: Promise.resolve() };
      // 今の場所の項目だけを書き換える（足さない）。hash は書き換えるだけで履歴を増やさない
      const here = places.current();
      if (isRef(slides[cur].id) && isOwn(here)) places.updateCurrent(slides[cur].id, curStep, curAdd);
      writeLocation(hashOf(cur, curStep));
      updatePaper();
      updatePosition();
      if (sideEl) {                                              // 左の列は、新しいデッキで作り直す
        sideEl.remove();
        sideEl = null; sideItems = []; sideAddItems = []; sideMarked = null;
        buildSide();
        updateSide();
      }
      notesShown = -1;
      updateNotes();
      memoId = null;                                             // メモの帯は、今のスライドの中身を読み直す
      updateMemo();
      markSideMemo();
      if (reopenOverview) openOverview();
      return { id: slides[cur].id, step: curStep };
    }
    const editor = window.slideEditor;
    if (editor && typeof editor.attach === 'function') editor.attach({ replaceDeck, place });
  }

  whenBodyReady(start);                                          // 上の定義がそろってから始める
})();
