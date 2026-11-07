#!/usr/bin/env python3
"""
スキー場の「積雪」「滑走可否」「滑走できるコース数」を公式サイトから読み取って、
data/snow.js を作り直すプログラム。

・AI は使っていない。決まったページを1回ずつ読んで、決まった場所の文字を拾うだけ。
・GitHub Actions が毎日1回、自動で動かす（.github/workflows/update-snow.yml）。
・Python の標準機能だけで動くので、何もインストールしなくてよい。

手元で試すとき（サイトのフォルダで実行）:
    python tools/update_snow.py

大事な決まり:
・読めなかったスキー場は、前回の数字を使い回さず「unknown」にする（ページには「公式サイトを確認」と出る）。
・知らない言葉が出てきたら、勝手に推測せず「unknown」にする。
・更新が止まっている古い情報は使わない（オフシーズンのページには春の積雪が残っているため）。
・滑走可否が読めなかったら、最後に失敗として終わる（GitHub がメールで知らせてくれる）。
・コース数だけが読めなかったときは「—」にするだけで、失敗にはしない。
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request

# ---------------------------------------------------------
# 設定
# ---------------------------------------------------------

# 読みに行くページ（1日に1回、1ページ1回だけ）
PAGES = {
    "zao": "https://zaomountainresort.com/area-information/",
    "madarao": "https://www.madarao.jp/ski/",
    "madarao_cond": "https://www.madarao.jp/ski/conditions",
    "shiga": "https://www.shigakogen.gr.jp/lift_information/",
    "hakuba": "https://www.hakubavalley.com/weather/",  # 白馬の5行の滑走可否と積雪はこの1ページで読める
    "okuibuki": "https://www.okuibuki.co.jp/gelande/",
    "biwako": "https://www.biwako-valley.com/winter",
    # ここから下は、白馬の各スキー場のコース数を読むページ
    "happo": "https://www.happo-one.jp/gelande/condition",
    "iwatake": "https://iwatake-mountain-resort.com/winter/course_lift/",
    "goryu": "https://www.hakubagoryu.jp/ski/gelande/slope-conditions/",  # 五竜と Hakuba47 の両方が載っている
    "cortina": "https://www.hgp.co.jp/cortina/ski/",
    # 栂池は、公式サイトの地図が別のアプリの埋め込みで、ページを読むだけではコース数が取れない（「—」になる）
}

USER_AGENT = "Mozilla/5.0 (compatible; SkiZekkeiBot/1.0; +https://gorouzaemon.github.io/wonderfulview/)"
TIMEOUT_SECONDS = 30      # 返事を待つ長さ
RETRY_WAIT_SECONDS = 5    # 失敗したときに、もう1回試すまでの待ち時間
PAUSE_SECONDS = 1         # ページとページの間の休み時間
MAX_AGE_DAYS = 2          # 何日前の情報までを「新しい」とみなすか
MOSTLY_RATIO = 0.7        # 全コースのうちこの割合以上が滑れたら「大部分可」（0.7 ＝ 7割）
MADARAO_TOTAL_COURSES = 32  # 斑尾の全コース数（公式の「25/32コース滑走可能」の分母）

JST = dt.timezone(dt.timedelta(hours=9))

FULL = "full"        # 全面可
MOSTLY = "mostly"    # 大部分可
PARTIAL = "partial"  # 一部可
CLOSED = "closed"    # クローズ
UNKNOWN = "unknown"  # 読めなかった（ページには「公式サイトを確認」と出る）

# 公式サイトの言葉 → 状態。ここに無い言葉が出てきたら「読めなかった」扱いになる。
# 新しい言葉が出てきたら、ここに1行足せばよい。

# スキー場全体の言葉（そのまま4段階になる）
HAKUBA_WORDS = {
    "全面可能": FULL,
    "大部分可能": MOSTLY,
    "一部可能": PARTIAL,
    "滑走不可": CLOSED,
    "閉鎖中": CLOSED,
    "今シーズン営業終了": CLOSED,
}

# コース（またはリフト）1本ごとの言葉（FULL＝滑れる、PARTIAL＝一部だけ滑れる、CLOSED＝滑れない）
ZAO_WORDS = {
    "滑走可": FULL,
    "一部滑走不可": PARTIAL,
    "一部滑走可": PARTIAL,
    "滑走不可": CLOSED,
    "シーズン終了": CLOSED,
}
SHIGA_WORDS = {
    "全面滑走可能": FULL,
    "一部滑走可能": PARTIAL,
    "閉鎖中": CLOSED,
    "滑走不可": CLOSED,
    "準備中": CLOSED,
}
BIWAKO_WORDS = {
    "オープン予定": FULL,
    "オープン": FULL,
    "○": FULL,
    "一部オープン": PARTIAL,
    "一部オープン予定": PARTIAL,
    "クローズ": CLOSED,
    "クローズ(調整中)": CLOSED,
    "準備中": CLOSED,
    "×": CLOSED,
    "冬季営業終了": CLOSED,
    "営業終了": CLOSED,
}
MADARAO_LIFT_WORDS = {
    "運行": FULL,  # ページには運行時間（8:30〜16:30 など）が書かれている
    "営業終了": CLOSED,
    "運休": CLOSED,
}
OKUIBUKI_COURSE_WORDS = {
    "OPEN": FULL,
    "CLOSE": CLOSED,
    "CLOSED": CLOSED,
    "○": FULL,
    "◯": FULL,
    "×": CLOSED,
}
HAPPO_COURSE_WORDS = {
    "○": FULL,
    "△": PARTIAL,  # 一部滑走不可
    "X": CLOSED,   # ページの「Ｘ」は全角なので、半角にそろえた形で書いている
    "×": CLOSED,
}
IWATAKE_COURSE_CLASSES = {
    "ok": FULL,
    "mid": PARTIAL,
    "ng": CLOSED,
}
# 五竜と Hakuba47：冬の表記はまだ確認できていない。知らない言葉ならコース数が「—」になるだけ
GORYU_COURSE_WORDS = {
    "滑走可": FULL,
    "滑走可能": FULL,
    "全面滑走可": FULL,
    "全面滑走可能": FULL,
    "オープン": FULL,
    "一部滑走可": PARTIAL,
    "一部滑走可能": PARTIAL,
    "一部滑走不可": PARTIAL,
    "滑走不可": CLOSED,
    "クローズ": CLOSED,
    "閉鎖": CLOSED,
    "閉鎖中": CLOSED,
    "営業終了": CLOSED,
}
# 五竜と Hakuba47 の表で数えない行（早朝・ナイターの時間帯の行と、「*」で始まるコースの細かい区間）
GORYU_SKIP_ROWS = re.compile(r"^\*|早朝営業|ナイター営業")
# 琵琶湖バレイの表で数えない行（ゲレンデのコースではないもの）
BIWAKO_SKIP_ROWS = re.compile(r"パーク|PARK|モーグル|MOGUL", re.IGNORECASE)


class Unreadable(Exception):
    """ページの形が予想と違って読み取れなかったときのエラー"""


# ---------------------------------------------------------
# 共通の小さな道具
# ---------------------------------------------------------

def squeeze(page):
    """スクリプト・スタイル・コメントを取り除き、改行や連続する空白を1つにまとめる"""
    page = re.sub(r"<script[\s\S]*?</script>", " ", page)
    page = re.sub(r"<style[\s\S]*?</style>", " ", page)
    page = re.sub(r"<!--[\s\S]*?-->", " ", page)
    return re.sub(r"\s+", " ", page)


def plain(fragment):
    """タグを取り除いて文字だけにする（全角の英数字は半角にそろえる）"""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = unicodedata.normalize("NFKC", html.unescape(text))
    return re.sub(r"\s+", " ", text).strip()


def to_date(text):
    """「2026/02/15 07:37」「2026.02.01」「2026-03-16 7:33 am」→ 日付（無ければ None）"""
    found = re.search(r"(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})", text)
    if not found:
        return None
    return dt.date(int(found.group(1)), int(found.group(2)), int(found.group(3)))


def to_cm(text):
    """「110cm」「300」→ 数字。「- cm」や空欄は None"""
    found = re.search(r"\d+", plain(text))
    return int(found.group()) if found else None


def first(pattern, text, what):
    """text の中から pattern の () の部分を探す。見つからなければ「読めなかった」にする"""
    found = re.search(pattern, text)
    if not found:
        raise Unreadable(f"{what}が見つからない")
    return found.group(1)


def tally(words, table):
    """コース1本ごとの言葉を数える。戻り値は (滑れる数, 一部だけ滑れる数, 滑れない数)"""
    if not words:
        raise Unreadable("コースの一覧が見つからない")
    counts = {FULL: 0, PARTIAL: 0, CLOSED: 0}
    for word in words:
        word = plain(word)
        if word not in table:
            raise Unreadable(f"知らない言葉「{word}」")
        counts[table[word]] += 1
    return counts[FULL], counts[PARTIAL], counts[CLOSED]


def judge(full, partial, closed):
    """コースの数から4段階を決める。全部滑れる＝全面可、7割以上＝大部分可、それ未満＝一部可、0＝クローズ"""
    total = full + partial + closed
    can_ski = full + partial
    if total == 0:
        raise Unreadable("コースの数が0")
    if full == total:
        return FULL
    if can_ski == 0:
        return CLOSED
    return MOSTLY if can_ski / total >= MOSTLY_RATIO else PARTIAL


def course_pair(full, partial, closed):
    """(滑れる数, 一部だけ滑れる数, 滑れない数) → (滑走できるコース数, 全コース数)"""
    return full + partial, full + partial + closed


def report(status, snow, date, courses=None):
    """読み取り結果。snow は [(積雪の数字, その数字の日付), ...]、date はページ全体の更新日、
    courses は (滑走できるコース数, 全コース数)"""
    return {"status": status, "snow": snow, "date": date, "courses": courses}


def is_new(date, today):
    """日付が新しければ True。ページに日付が書かれていない（None）ときも True"""
    return date is None or (today - date).days <= MAX_AGE_DAYS


def apply_age_rule(result, today):
    """古い情報を取り除く。戻り値は (状態, 積雪の数字のリスト)"""
    status = result["status"]
    # 「滑走できる」という情報が古いときは信用しない。
    # 「クローズ」のほうはオフシーズンにページの更新が止まっていても正しいのでそのまま。
    if status in (FULL, MOSTLY, PARTIAL) and not is_new(result["date"], today):
        status = UNKNOWN
    snow = [value for value, date in result["snow"] if value is not None and is_new(date, today)]
    return status, snow


def course_label(pair, date, status, today):
    """(6, 16) → 「6/16」。古い情報や、滑走可否と食い違うときは None（ページには「—」と出る）"""
    if pair is None or status == UNKNOWN:
        return None
    can_ski, total = pair
    if can_ski > 0 and not is_new(date, today):
        return None
    if (status == CLOSED) != (can_ski == 0):
        return None
    return f"{can_ski}/{total}"


def merge_status(statuses):
    """1行に2つのスキー場をまとめるとき（白馬47＆五竜）の状態。低いほうに合わせる"""
    if UNKNOWN in statuses:
        return UNKNOWN
    if len(set(statuses)) == 1:
        return statuses[0]
    # 片方がクローズでも、もう片方が滑れるなら「一部可」
    if CLOSED in statuses:
        return PARTIAL
    return PARTIAL if PARTIAL in statuses else MOSTLY


def snow_label(values):
    """[70, 180] → 「70〜180cm」、[150] → 「150cm」、[] → None"""
    if not values:
        return None
    low, high = min(values), max(values)
    return f"{low}cm" if low == high else f"{low}〜{high}cm"


# ---------------------------------------------------------
# スキー場ごとの読み取り（滑走可否と積雪）
# ---------------------------------------------------------

def read_zao(page):
    """蔵王温泉：コースごとの滑走可否と、エリアごとの積雪・更新日時の表"""
    page = squeeze(page)
    counts = tally(re.findall(r'<td class="kahi"[^>]*>(.*?)</td>', page), ZAO_WORDS)
    areas = re.findall(r'<td class="sekisetsu"[^>]*>(.*?)</td>\s*<td class="date"[^>]*>(.*?)</td>', page)
    snow = [(to_cm(cell), to_date(when)) for cell, when in areas]
    dates = [date for _, date in snow if date]
    if not dates:
        raise Unreadable("更新日時が見つからない")
    return report(judge(*counts), snow, max(dates), course_pair(*counts))


def madarao_course_count(page, conditions, date):
    """斑尾の文章からコース数を探す。書き方が日によって違うので順番に試す。無ければ None"""
    pattern = r"(\d+)\s*/\s*(\d+)\s*コース\s*滑走可能"
    found = re.search(pattern, plain(page))  # 例：25/32コース滑走可能で営業予定です
    if found:
        return int(found.group(1)), int(found.group(2))

    # 詳細ページは同じ日に更新されたものだけ使う
    if to_date(plain(first(r'<p class="is-center t-small">(.*?)</p>', conditions, "詳細ページの更新日"))) != date:
        return None
    found = re.search(pattern, plain(conditions))
    if found:
        return int(found.group(1)), int(found.group(2))

    cell = re.search(r'flex-table-head[^"]*">滑走可能コース</div>\s*<div class="flex-table-cell[^"]*">(.*?)</div>', conditions)
    if not cell:
        return None
    found = re.search(r"(\d+)\s*コース\s*滑走可能", plain(cell.group(1)))  # 例：ツリーランコース含む31コース滑走可能
    if found:
        can_ski = int(found.group(1))
    else:
        can_ski = len(re.findall(r"[①-⑳㉑-㉟]", cell.group(1)))  # 例：①パラダイス ②初心者A ...
    if not 0 < can_ski <= MADARAO_TOTAL_COURSES:
        return None
    return can_ski, MADARAO_TOTAL_COURSES


def read_madarao(page, conditions):
    """斑尾高原：文章のコース数を優先し、書かれていないときはリフトの運行表で判断する"""
    page = squeeze(page)
    conditions = squeeze(conditions)
    date = to_date(first(r"本日のゲレンデ状況</dt>\s*<dd>(.*?)</dd>", page, "更新日"))
    snow = [(to_cm(first(r"<dt>積雪</dt>\s*<dd>(.*?)</dd>", page, "積雪")), date)]

    lift_table = first(r"リフト運行予定</th>(.*?)(?:table-head|</table>)", page, "リフトの表")
    cells = re.findall(r"<tr>\s*<th[^>]*>.*?</th>\s*<td[^>]*>(.*?)</td>", lift_table)
    words = ["運行" if re.search(r"\d{1,2}:\d{2}", plain(cell)) else cell for cell in cells]
    lifts = tally(words, MADARAO_LIFT_WORDS)
    if judge(*lifts) == CLOSED:
        # リフトが全部止まっていれば、文章に何と書いてあってもクローズ
        return report(CLOSED, snow, date, (0, MADARAO_TOTAL_COURSES))

    try:
        pair = madarao_course_count(page, conditions, date)
    except Unreadable as error:
        print(f"斑尾のコース数: {error}")
        pair = None
    if pair:
        can_ski, total = pair
        return report(judge(can_ski, 0, total - can_ski), snow, date, pair)
    return report(judge(*lifts), snow, date)


def read_shiga(page):
    """志賀高原：18のスキー場ごとのコース一覧と積雪。更新日はページに書かれていない"""
    sections = re.split(r'<section id="seg-\d+"', squeeze(page))[1:]
    if len(sections) < 10:
        raise Unreadable("スキー場の区切りが見つからない")
    words = []
    snow = []
    for section in sections:
        cell = re.search(r"<dt>積雪</dt>\s*<dd>(.*?)</dd>", section)
        if cell:
            snow.append((to_cm(cell.group(1)), None))
        courses = re.search(r'--course">(.*?)(?=p-sakudo-status-segment|$)', section)
        if courses:
            words += re.findall(r'class="status --status-\d+">(.*?)</span>', courses.group(1))
    counts = tally(words, SHIGA_WORDS)
    return report(judge(*counts), snow, None, course_pair(*counts))


def read_hakuba(page, slug):
    """白馬バレーの公式ページ：スキー場ごとの滑走可否・積雪。slug は detail_xxx の xxx"""
    page = squeeze(page)
    for item in page.split('<div class="report-item">')[1:]:
        if re.search(rf'/weather/detail_{slug}/?"', item):
            break
    else:
        raise Unreadable(f"{slug} の欄が見つからない")

    name = first(r'gelande_name">(.*?)</h3>', item, "スキー場名").strip()
    label = plain(first(
        r'slope_status">\s*<span class="status-item">.*?</span>\s*<span class="status-label[^"]*">(.*?)</span>',
        item, "滑走可否"))
    label = label.strip("[] ")
    date = to_date(first(r'class="date">(.*?)</span>', item, "更新日時"))
    snow = [(to_cm(first(r'snow_status">\s*<span class="status-item">(.*?)</span>', item, "積雪")), date)]

    if label:
        if label not in HAKUBA_WORDS:
            raise Unreadable(f"知らない言葉「{label}」")
        return report(HAKUBA_WORDS[label], snow, date)

    # シーズン前は滑走可否が空欄になる。リフトが全部止まっていればクローズとみなす
    for lift_item in page.split('<div class="lift-item')[1:]:
        if f"<h3>{name}</h3>" in lift_item:
            lifts = set(re.findall(r'<tr class="status_(\w+)">', lift_item))
            if lifts == {"closed"}:
                return report(CLOSED, snow, date)
            raise Unreadable("滑走可否が空欄なのにリフトの状態がクローズではない")
    raise Unreadable(f"{name} のリフトの表が見つからない")


def read_okuibuki(page):
    """奥伊吹：「本日の営業」が CLOSE ならクローズ。OPEN ならコースごとの印を数える"""
    page = squeeze(page)
    word = plain(first(r'lcl-open-item__status">(.*?)</em>', page, "本日の営業"))
    date_text = "{}/{}/{}".format(
        first(r'lcl-open-year__num">\s*(\d{4})', page, "年"),
        first(r'lcl-open-date__month">\s*(\d{1,2})', page, "月"),
        first(r'lcl-open-date__day">\s*(\d{1,2})', page, "日"),
    )
    date = to_date(date_text)
    snow = [(to_cm(first(r'lcl-open-item__ttl">積雪</dt>\s*<dd[^>]*>(.*?)</dd>', page, "積雪")), date)]
    marks = re.findall(r'<div class="lcl-course__status">(.*?)</div>', page)

    if word in ("CLOSE", "CLOSED"):
        return report(CLOSED, snow, date, (0, len(marks)) if marks else None)
    if word != "OPEN":
        raise Unreadable(f"知らない言葉「{word}」")

    words = []
    for mark in marks:
        if not mark.strip():
            words.append("×")  # 何も書かれていないコースはオープンしていない
        elif plain(mark):
            words.append(plain(mark))
        elif re.search(r"circle|maru|open", mark, re.IGNORECASE):
            words.append("○")  # 文字のない丸印のアイコン
        else:
            raise Unreadable("コースの印の意味が分からない")
    counts = tally(words, OKUIBUKI_COURSE_WORDS)
    if judge(*counts) == CLOSED:
        raise Unreadable("OPEN の日なのにコースの印がひとつもない")
    return report(judge(*counts), snow, date, course_pair(*counts))


def read_biwako(page):
    """琵琶湖バレイ：コース営業情報の表と、「本日の情報」の文章に書かれた積雪"""
    page = squeeze(page)
    table = first(r'(<table id="tablepress-5".*?</table>)', page, "コースの表")
    words = []
    for name, word in re.findall(r'<td class="column-1">(.*?)</td>\s*<td class="column-2">(.*?)</td>', table):
        name = plain(name)
        if "◇" in name:
            break  # ここから下はスノーパークなど（ゲレンデのコースではない）
        if name and not BIWAKO_SKIP_ROWS.search(name):
            words.append(word)
    counts = tally(words, BIWAKO_WORDS)
    status = judge(*counts)
    date = to_date(first(r'up_date_time">(.*?)</div>', page, "更新日時"))

    snow = []
    if status != CLOSED:
        today_text = plain(first(r"today__scroll-area(.*?)up_date_time", page, "本日の情報"))
        found = re.search(r"積雪\s*:?\s*(\d+)\s*(?:cm|センチ)", today_text)
        if found:
            snow.append((int(found.group(1)), date))
    return report(status, snow, date, course_pair(*counts))


# ---------------------------------------------------------
# 白馬のスキー場のコース数（戻り値は ((滑走できるコース数, 全コース数), 更新日)）
# ---------------------------------------------------------

def read_happo_courses(page):
    """白馬八方尾根：コース表の印（○ △ Ｘ）を数える"""
    page = squeeze(page)
    table = first(r'(<table summary="ゲレンデ状況".*?</table>)', page, "コースの表")
    cells = re.findall(r"<tr>\s*<td>[^<]*</td>\s*<td>[^<]*</td>\s*<td>(.*?)</td>", table)
    words = [first(r'alt="([^"]*)"', cell, "コースの印") for cell in cells]
    date = to_date(first(r'update-time">(.*?)</p>', page, "更新日"))
    return course_pair(*tally(words, HAPPO_COURSE_WORDS)), date


def read_iwatake_courses(page):
    """白馬岩岳：マウンテンサイドとビレッジサイドのコース表を数える（クロスカントリーコースは数えない）"""
    page = squeeze(page)
    words = []
    for table_id in ("course_states_list_mountain", "course_states_list_village"):
        table = first(rf'<table[^>]*id="{table_id}"(.*?)</table>', page, "コースの表")
        for row in re.findall(r"<tr>(.*?)</tr>", table):
            state = re.search(r'<td class="course_state (\w+)">', row)
            if state and "クロスカントリー" not in row:
                words.append(state.group(1))
    date = to_date(first(r'course_update_data">(.*?)</span>', page, "更新日"))
    return course_pair(*tally(words, IWATAKE_COURSE_CLASSES)), date


def read_goryu_courses(page):
    """白馬47＆五竜：アルプス平/とおみ・いいもり・Hakuba47 の3つの表を合わせて数える"""
    blocks = squeeze(page).split("c-status-table__heading")[1:]
    if len(blocks) < 3:
        raise Unreadable("コースの表が足りない")
    can_ski = total = 0
    oldest_open = None  # 滑れるコースがある表のうち、いちばん古い更新日
    for block in blocks:
        date = to_date(first(r'c-status-table__update">(.*?)</p>', block, "更新日"))
        rows = re.findall(r'<td>((?:(?!</?td).)*)</td>\s*<td>\s*<p class="status[^"]*">(.*?)</p>', block)
        words = [word for name, word in rows if not GORYU_SKIP_ROWS.search(plain(name))]
        here_can_ski, here_total = course_pair(*tally(words, GORYU_COURSE_WORDS))
        can_ski += here_can_ski
        total += here_total
        if here_can_ski and (oldest_open is None or date < oldest_open):
            oldest_open = date
    return (can_ski, total), oldest_open


def read_cortina_courses(page, today):
    """白馬コルチナ：トップページの「コース 15 / 16」。日付は月/日しか書かれていない"""
    page = squeeze(page)
    count = plain(first(r'<p class="sst">コース</p>\s*<p class="now">(.*?)</p>', page, "コース数"))
    found = re.fullmatch(r"(\d+)\s*/\s*(\d+)", count)
    if not found:
        raise Unreadable(f"コース数の形が違う「{count}」")
    month, day = first(r'<p class="day">\s*(\d{1,2}/\d{1,2})', page, "日付").split("/")
    date = dt.date(today.year, int(month), int(day))
    if date > today + dt.timedelta(days=1):
        date = date.replace(year=today.year - 1)  # 年をまたいだとき
    return (int(found.group(1)), int(found.group(2))), date


def need(pages, key):
    """ページの中身を取り出す（取得に失敗していたら「読めなかった」にする）"""
    if pages.get(key) is None:
        raise Unreadable(f"{key} のページを取得できなかった")
    return pages[key]


def hakuba(slug):
    return lambda pages: read_hakuba(need(pages, "hakuba"), slug)


# 表に並べるスキー場（ここに書いた順番で表示する）。
# readers は滑走可否と積雪、courses は白馬のようにコース数を別のページから読むとき。
# スキー場を増やすときは、読み取りの関数を作ってここに足す。
RESORTS = [
    {
        "id": "zao", "name": "蔵王温泉", "page": "zao.html", "official": PAGES["zao"],
        "readers": [lambda pages: read_zao(need(pages, "zao"))],
    },
    {
        "id": "madarao", "name": "斑尾高原", "page": "madarao.html", "official": PAGES["madarao_cond"],
        "readers": [lambda pages: read_madarao(need(pages, "madarao"), pages.get("madarao_cond") or "")],
    },
    {
        "id": "shiga", "name": "志賀高原", "page": "shiga.html", "official": PAGES["shiga"],
        "readers": [lambda pages: read_shiga(need(pages, "shiga"))],
    },
    {
        "id": "cortina", "name": "白馬コルチナ", "page": "cortina.html",
        "official": "https://www.hakubavalley.com/weather/detail_cortina/",
        "readers": [hakuba("cortina")],
        "courses": lambda pages, today: read_cortina_courses(need(pages, "cortina"), today),
    },
    {
        "id": "tsugaike", "name": "栂池高原", "page": "tsugaike.html",
        "official": "https://www.hakubavalley.com/weather/detail_tsugaike/",
        "readers": [hakuba("tsugaike")],
    },
    {
        "id": "iwatake", "name": "白馬岩岳", "page": "iwatake.html",
        "official": "https://www.hakubavalley.com/weather/detail_iwatake/",
        "readers": [hakuba("iwatake")],
        "courses": lambda pages, today: read_iwatake_courses(need(pages, "iwatake")),
    },
    {
        "id": "happo", "name": "白馬八方尾根", "page": "happo.html",
        "official": "https://www.hakubavalley.com/weather/detail_happo/",
        "readers": [hakuba("happo")],
        "courses": lambda pages, today: read_happo_courses(need(pages, "happo")),
    },
    {
        "id": "goryu", "name": "白馬47＆五竜", "page": "goryu.html", "official": PAGES["hakuba"],
        "readers": [hakuba("goryu"), hakuba("hakuba47")],
        "courses": lambda pages, today: read_goryu_courses(need(pages, "goryu")),
    },
    {
        "id": "okuibuki", "name": "奥伊吹", "page": "okuibuki.html", "official": PAGES["okuibuki"],
        "readers": [lambda pages: read_okuibuki(need(pages, "okuibuki"))],
    },
    {
        "id": "biwako", "name": "琵琶湖バレイ", "page": "biwako.html", "official": PAGES["biwako"],
        "readers": [lambda pages: read_biwako(need(pages, "biwako"))],
    },
]


# ---------------------------------------------------------
# ページの取得と、data/snow.js の書き出し
# ---------------------------------------------------------

def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def download_pages():
    """全ページを1回ずつ取得する（失敗したら1回だけ、少し待ってやり直す）"""
    pages = {}
    for key, url in PAGES.items():
        pages[key] = None
        for attempt in (1, 2):
            try:
                pages[key] = fetch(url)
                print(f"取得OK {url}")
                break
            except Exception as error:
                print(f"取得失敗（{attempt}回目） {url} : {error}")
                if attempt == 1:
                    time.sleep(RETRY_WAIT_SECONDS)
        time.sleep(PAUSE_SECONDS)
    return pages


def load_saved_pages(folder):
    """テスト用：保存しておいたページ（zao.html など）を読み込む"""
    pages = {}
    for key in PAGES:
        path = os.path.join(folder, key + ".html")
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as file:
                pages[key] = file.read()
    return pages


def read_courses(resort, results, pages, today):
    """コース数を読む。読めなくても失敗にはしない（ページには「—」と出る）"""
    if "courses" in resort:
        try:
            return resort["courses"](pages, today)
        except Exception as error:
            print(f"コース数を読めなかった: {resort['name']} : {error}")
            return None, None
    return results[0]["courses"], results[0]["date"]


def build_row(resort, pages, today):
    """スキー場1行ぶんのデータを作る。どこかで失敗したら unknown にする"""
    row = {key: resort[key] for key in ("id", "name", "page", "official")}
    try:
        results = [read(pages) for read in resort["readers"]]
        checked = [apply_age_rule(result, today) for result in results]
        row["snow"] = snow_label([value for _, values in checked for value in values])
        row["status"] = merge_status([status for status, _ in checked])
        pair, date = read_courses(resort, results, pages, today)
        row["courses"] = course_label(pair, date, row["status"], today)
    except Exception as error:  # 1つのスキー場の失敗で全体を止めない
        print(f"読めなかった: {resort['name']} : {error}")
        row["snow"] = None
        row["status"] = UNKNOWN
        row["courses"] = None
    return row


def build_data(pages, now):
    return {
        "updatedAt": now.isoformat(timespec="seconds"),
        "updatedLabel": f"{now.month}月{now.day}日 {now.hour}時{now.minute}分",
        "resorts": [build_row(resort, pages, now.date()) for resort in RESORTS],
    }


def write_data(data, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write("// このファイルは tools/update_snow.py が毎日自動で書き換えます（手で直さなくてOK）\n")
        file.write(f"window.SNOW_DATA = {body};\n")


def main():
    sys.stdout.reconfigure(errors="replace")  # 表示できない文字があっても止まらないように

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description="スキー場の積雪・滑走可否・コース数を読み取って data/snow.js を作る")
    parser.add_argument("--output", default=os.path.join(root, "data", "snow.js"), help="書き出すファイル")
    parser.add_argument("--from-dir", help="テスト用：ネットに行かず、このフォルダに保存したページを読む")
    parser.add_argument("--today", help="テスト用：今日の日付を YYYY-MM-DD で指定する")
    args = parser.parse_args()

    now = dt.datetime.now(JST)
    if args.today:
        now = dt.datetime.combine(dt.date.fromisoformat(args.today), dt.time(9, 17), JST)

    pages = load_saved_pages(args.from_dir) if args.from_dir else download_pages()
    data = build_data(pages, now)
    write_data(data, args.output)

    print(f"--- {data['updatedLabel']} 時点 ---")
    for row in data["resorts"]:
        print(f"{row['name']}: 積雪={row['snow'] or '-'} 滑走可否={row['status']} コース={row['courses'] or '-'}")

    failed = [row["name"] for row in data["resorts"] if row["status"] == UNKNOWN]
    if failed:
        print("読めなかったスキー場: " + "、".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
