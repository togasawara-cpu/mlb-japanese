"""
MLB日本人選手 前日成績取得スクリプト v2

新デザインのダッシュボードHTMLを自動生成する。
- 8選手のシーズン成績、直近試合、ハイライト動画をMLB Stats APIから取得
- カラフルなカード型レイアウトの docs/index.html を生成
- stats_data.json と highlights.json も同時出力（参照キャッシュ）
"""

from __future__ import annotations

import html as html_mod
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

API = "https://statsapi.mlb.com/api/v1"
JST = timezone(timedelta(hours=9))
SEASON = 2026
TIMEOUT = 20

# SpoTVnow JAPAN 公式 YouTube チャンネル（日本語実況のMLBハイライト）
SPOTV_CHANNEL_ID = "UCJ-l-sMQFHogSy8KXRyMIRA"
SPOTV_RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={SPOTV_CHANNEL_ID}"
ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_HTML = ROOT / "docs" / "index.html"
OUTPUT_STATS_JSON = ROOT / "stats_data.json"
OUTPUT_HIGHLIGHTS_JSON = ROOT / "highlights.json"

# 対象選手 (8名)
PLAYERS: list[dict[str, Any]] = [
    {"key": "ohtani",   "id": 660271, "name_ja": "大谷 翔平",  "name_en": "Shohei Ohtani",
     "jersey": "17", "team_code": "LAD", "team_full": "LOS ANGELES DODGERS", "team_jp": "ドジャース",
     "team_class": "dodgers",  "position": "DH/SP",
     "is_pitcher": True,  "is_hitter": True,  "two_way": True},
    {"key": "yamamoto", "id": 680781, "name_ja": "山本 由伸",  "name_en": "Yoshinobu Yamamoto",
     "jersey": "18", "team_code": "LAD", "team_full": "LOS ANGELES DODGERS", "team_jp": "ドジャース",
     "team_class": "dodgers",  "position": "SP",
     "is_pitcher": True,  "is_hitter": False},
    {"key": "imanaga",  "id": 684007, "name_ja": "今永 昇太",  "name_en": "Shota Imanaga",
     "jersey": "18", "team_code": "CHC", "team_full": "CHICAGO CUBS", "team_jp": "カブス",
     "team_class": "cubs",     "position": "SP",
     "is_pitcher": True,  "is_hitter": False},
    {"key": "suzuki",   "id": 673548, "name_ja": "鈴木 誠也",  "name_en": "Seiya Suzuki",
     "jersey": "27", "team_code": "CHC", "team_full": "CHICAGO CUBS", "team_jp": "カブス",
     "team_class": "cubs",     "position": "OF",
     "is_pitcher": False, "is_hitter": True},
    {"key": "yoshida",  "id": 807799, "name_ja": "吉田 正尚",  "name_en": "Masataka Yoshida",
     "jersey": "7",  "team_code": "BOS", "team_full": "BOSTON RED SOX", "team_jp": "レッドソックス",
     "team_class": "redsox",   "position": "DH/OF",
     "is_pitcher": False, "is_hitter": True},
    {"key": "okamoto",  "id": 672960, "name_ja": "岡本 和真",  "name_en": "Kazuma Okamoto",
     "jersey": "7",  "team_code": "TOR", "team_full": "TORONTO BLUE JAYS", "team_jp": "ブルージェイズ",
     "team_class": "bluejays", "position": "3B",
     "is_pitcher": False, "is_hitter": True},
    {"key": "murakami", "id": 808959, "name_ja": "村上 宗隆",  "name_en": "Munetaka Murakami",
     "jersey": "5",  "team_code": "CWS", "team_full": "CHICAGO WHITE SOX", "team_jp": "ホワイトソックス",
     "team_class": "whitesox", "position": "3B",
     "is_pitcher": False, "is_hitter": True},
    {"key": "matsui",   "id": 673513, "name_ja": "松井 裕樹",  "name_en": "Yuki Matsui",
     "jersey": "1",  "team_code": "SD",  "team_full": "SAN DIEGO PADRES", "team_jp": "パドレス",
     "team_class": "padres",   "position": "RP",
     "is_pitcher": True,  "is_hitter": False},
]

# 対戦相手のチーム名→3文字略称
TEAM_CODES: dict[str, str] = {
    "Arizona Diamondbacks": "ARI", "Atlanta Braves": "ATL", "Baltimore Orioles": "BAL",
    "Boston Red Sox": "BOS",       "Chicago Cubs": "CHC",   "Chicago White Sox": "CWS",
    "Cincinnati Reds": "CIN",      "Cleveland Guardians": "CLE", "Colorado Rockies": "COL",
    "Detroit Tigers": "DET",       "Houston Astros": "HOU", "Kansas City Royals": "KC",
    "Los Angeles Angels": "LAA",   "Los Angeles Dodgers": "LAD", "Miami Marlins": "MIA",
    "Milwaukee Brewers": "MIL",    "Minnesota Twins": "MIN", "New York Mets": "NYM",
    "New York Yankees": "NYY",     "Oakland Athletics": "OAK", "Athletics": "OAK",
    "Philadelphia Phillies": "PHI", "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD",
    "San Francisco Giants": "SF",  "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL",
    "Tampa Bay Rays": "TB",        "Texas Rangers": "TEX",  "Toronto Blue Jays": "TOR",
    "Washington Nationals": "WSH",
}


def team_code(name: str) -> str:
    return TEAM_CODES.get(name, name[:3].upper() if name else "")


# ---------------------------------------------------------------------------
# API 呼び出し
# ---------------------------------------------------------------------------

def fetch_season_stats(player_id: int, group: str) -> dict[str, Any]:
    url = f"{API}/people/{player_id}/stats"
    params = {"stats": "season", "group": group, "season": SEASON}
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        for s in r.json().get("stats", []):
            splits = s.get("splits", [])
            if splits:
                return splits[0].get("stat", {})
    except requests.RequestException as e:
        print(f"[WARN] season {player_id}/{group}: {e}", file=sys.stderr)
    return {}


def fetch_last_game(player_id: int, group: str) -> dict[str, Any] | None:
    url = f"{API}/people/{player_id}/stats"
    params = {"stats": "gameLog", "group": group, "season": SEASON}
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        for s in r.json().get("stats", []):
            splits = s.get("splits", [])
            if splits:
                last = splits[-1]
                return {
                    "date": last.get("date", ""),
                    "opp": last.get("opponent", {}).get("name", ""),
                    "stat": last.get("stat", {}),
                    "gamePk": last.get("game", {}).get("gamePk"),
                }
    except requests.RequestException as e:
        print(f"[WARN] gameLog {player_id}/{group}: {e}", file=sys.stderr)
    return None


def pick_mp4(playbacks: list[dict[str, Any]]) -> str:
    for pb in playbacks:
        u = pb.get("url", "")
        if "1280x720" in u and u.endswith(".mp4"):
            return u
    for pb in playbacks:
        u = pb.get("url", "")
        if u.endswith(".mp4"):
            return u
    return ""


def pick_thumb(cuts: Any) -> str:
    cuts_list = list(cuts.values()) if isinstance(cuts, dict) else (cuts or [])
    for cut in cuts_list:
        src = cut.get("src", "")
        if "1920" in src:
            return src
    return cuts_list[0].get("src", "") if cuts_list else ""


# SpoTVnow YouTube ハイライト
def fetch_youtube_videos() -> list[dict[str, str]]:
    """SpoTVnowの最新公開動画(最大15件)をRSSから取得"""
    try:
        r = requests.get(SPOTV_RSS_URL, timeout=TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        videos: list[dict[str, str]] = []
        for entry in root.findall("atom:entry", ATOM_NS):
            vid_el = entry.find("yt:videoId", ATOM_NS)
            title_el = entry.find("atom:title", ATOM_NS)
            pub_el = entry.find("atom:published", ATOM_NS)
            if vid_el is None or title_el is None:
                continue
            videos.append({
                "videoId": vid_el.text or "",
                "title": title_el.text or "",
                "published": (pub_el.text or "")[:10] if pub_el is not None else "",
            })
        return videos
    except (requests.RequestException, ET.ParseError) as e:
        print(f"[WARN] SpoTVnow RSS failed: {e}", file=sys.stderr)
        return []


def find_youtube_video(videos: list[dict[str, str]],
                       player: dict[str, Any],
                       game_date_str: str,
                       kind: str) -> dict[str, Any] | None:
    """RSS動画リストから選手の試合に該当する動画を1つ選ぶ。

    マッチング条件:
    1. タイトルに 'M.D' 形式の試合日が含まれる
    2. タイトルに自チームの日本語名が含まれる
    3. shorts は除外
    優先順位: 投球ダイジェスト(投手) > 試合ハイライト > 選手名一致
    """
    try:
        d = datetime.strptime(game_date_str, "%Y-%m-%d")
        date_pat = f"{d.month}.{d.day}"
    except (ValueError, TypeError):
        return None

    surname = player["name_ja"].split()[0]  # 「大谷 翔平」→「大谷」
    own_jp = player.get("team_jp", "")

    candidates: list[tuple[int, dict[str, str]]] = []
    for v in videos:
        title = v.get("title", "")
        if "#shorts" in title.lower():
            continue
        if date_pat not in title:
            continue
        if own_jp and own_jp not in title:
            continue
        score = 0
        if kind == "pitching" and "投球ダイジェスト" in title:
            score += 100
        elif "試合ハイライト" in title:
            score += 80
        if surname in title:
            score += 50
        candidates.append((score, v))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0][1]
    return {
        "source": "youtube",
        "videoId": best["videoId"],
        "title": best["title"],
        "published": best.get("published", ""),
    }


def fetch_highlight(game_pk: int) -> dict[str, Any] | None:
    if not game_pk:
        return None
    url = f"{API}/game/{game_pk}/content"
    try:
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        items = r.json().get("highlights", {}).get("highlights", {}).get("items", [])
        if not items:
            return None
        # recap（試合まとめ）を優先、なければ最初の項目
        recap = next(
            (it for it in items
             if "recap" in (it.get("title", "") + it.get("headline", "")).lower()),
            None,
        )
        item = recap or items[0]
        return {
            "title": item.get("headline", ""),
            "blurb": item.get("description", item.get("headline", "")),
            "date": (item.get("date", "") or "")[:10],
            "mp4": pick_mp4(item.get("playbacks", [])),
            "thumb": pick_thumb(item.get("image", {}).get("cuts", [])),
            "gamePk": game_pk,
        }
    except requests.RequestException as e:
        print(f"[WARN] highlight {game_pk}: {e}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# データ収集
# ---------------------------------------------------------------------------

def collect_data() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    stats_out: list[dict[str, Any]] = []
    highlights_out: dict[str, dict[str, Any]] = {}

    # SpoTVnow YouTube 動画一覧（最新15件）を一度だけ取得
    yt_videos = fetch_youtube_videos()
    print(f"[INFO] SpoTVnow RSS: {len(yt_videos)} videos", file=sys.stderr)

    for p in PLAYERS:
        print(f"[INFO] {p['name_ja']} ...", file=sys.stderr)
        season: dict[str, Any] = {}
        last_game: dict[str, Any] = {}

        if p["is_hitter"]:
            h = fetch_season_stats(p["id"], "hitting")
            if h:
                season["hitting"] = h
            lg = fetch_last_game(p["id"], "hitting")
            if lg:
                last_game["hitting"] = lg
        if p["is_pitcher"]:
            pi = fetch_season_stats(p["id"], "pitching")
            if pi:
                season["pitching"] = pi
            lg = fetch_last_game(p["id"], "pitching")
            if lg:
                last_game["pitching"] = lg

        # 直近試合のうち最新のgamePk・日付・kindを特定
        latest_pk: int | None = None
        latest_date = ""
        latest_kind = ""
        for kind in ("hitting", "pitching"):
            lg = last_game.get(kind)
            if lg and lg.get("date", "") > latest_date:
                latest_date = lg["date"]
                latest_pk = lg.get("gamePk")
                latest_kind = kind

        if latest_date:
            # 1. SpoTVnow YouTube を優先
            yt = find_youtube_video(yt_videos, p, latest_date, latest_kind)
            if yt:
                yt["game_date"] = latest_date
                highlights_out[p["key"]] = yt
                print(f"[OK]   {p['name_ja']}: YouTube → {yt['title'][:40]}...", file=sys.stderr)
            elif latest_pk:
                # 2. フォールバック: MLB公式の試合ハイライト
                hl = fetch_highlight(latest_pk)
                if hl and hl.get("mp4"):
                    hl["source"] = "mlb"
                    hl["game_date"] = latest_date
                    highlights_out[p["key"]] = hl
                    print(f"[OK]   {p['name_ja']}: MLB fallback", file=sys.stderr)

        stats_out.append({
            "key": p["key"],
            "name": p["name_en"],
            "jersey": p["jersey"],
            "season": season,
            "lastGame": last_game,
        })

    return stats_out, highlights_out


# ---------------------------------------------------------------------------
# HTML レンダリング
# ---------------------------------------------------------------------------

def fmt_jp_date(date_str: str) -> str:
    """2026-04-29 → 4月29日"""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.month}月{d.day}日"
    except Exception:
        return date_str


def fmt_short_date(date_str: str) -> str:
    """2026-04-29 → 4/29"""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.month}/{d.day}"
    except Exception:
        return date_str


def fmt_us_date_caps(d: datetime) -> str:
    """APR 30, 2026"""
    return f"{d.strftime('%b').upper()} {d.day}, {d.year}"


def fmt_us_date(d: datetime) -> str:
    """May 1, 2026"""
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def render_stat_line(kind: str, stat: dict[str, Any]) -> str:
    if kind == "hitting":
        return (
            f"<strong>{stat.get('hits', 0)}-{stat.get('atBats', 0)}</strong>"
            f" · BB {stat.get('baseOnBalls', 0)}"
            f" · K {stat.get('strikeOuts', 0)}"
        )
    # pitching
    marker = ""
    if stat.get("wins", 0) > 0:
        marker = " ○"
    elif stat.get("losses", 0) > 0:
        marker = " ●"
    return (
        f"<strong>{stat.get('inningsPitched', '0.0')}回</strong>"
        f" · {stat.get('hits', 0)}被安打"
        f" · {stat.get('strikeOuts', 0)}K"
        f" · {stat.get('baseOnBalls', 0)}BB"
        f" · <strong>{stat.get('earnedRuns', 0)}自責</strong>"
        f"{marker}"
    )


def render_batting_block(h: dict[str, Any]) -> str:
    return f"""            <div class="block-label">2026 SEASON · BATTING</div>
            <div class="stat-grid">
              <div class="cell"><span class="num">{h.get('avg', '-')}</span><span class="lbl">AVG</span></div>
              <div class="cell"><span class="num">{h.get('homeRuns', 0)}</span><span class="lbl">HR</span></div>
              <div class="cell"><span class="num">{h.get('rbi', 0)}</span><span class="lbl">RBI</span></div>
              <div class="cell"><span class="num">{h.get('ops', '-')}</span><span class="lbl">OPS</span></div>
            </div>"""


def render_pitching_block(pi: dict[str, Any], with_top_margin: bool = False) -> str:
    wl = f"{pi.get('wins', 0)}-{pi.get('losses', 0)}"
    style = ' style="margin-top:10px"' if with_top_margin else ""
    return f"""            <div class="block-label"{style}>2026 SEASON · PITCHING</div>
            <div class="stat-grid pit">
              <div class="cell"><span class="num">{wl}</span><span class="lbl">W-L</span></div>
              <div class="cell"><span class="num">{pi.get('era', '-')}</span><span class="lbl">ERA</span></div>
              <div class="cell"><span class="num">{pi.get('strikeOuts', 0)}</span><span class="lbl">K</span></div>
              <div class="cell"><span class="num">{pi.get('whip', '-')}</span><span class="lbl">WHIP</span></div>
            </div>"""


def render_last_game(p: dict[str, Any], last_game: dict[str, Any]) -> str:
    has_hit = "hitting" in last_game
    has_pit = "pitching" in last_game
    if not has_hit and not has_pit:
        return ""

    lines: list[str] = []

    if p.get("two_way") and has_hit and has_pit:
        # 大谷: 打席と登板の両方を新しい順で
        items = [
            (last_game["hitting"].get("date", ""), "打席", "hitting", last_game["hitting"]),
            (last_game["pitching"].get("date", ""), "登板", "pitching", last_game["pitching"]),
        ]
        items.sort(key=lambda x: x[0], reverse=True)
        for i, (_, label, kind, lg) in enumerate(items):
            margin = ' style="margin-top:6px"' if i > 0 else ""
            d = fmt_jp_date(lg.get("date", ""))
            opp = team_code(lg.get("opp", ""))
            line = render_stat_line(kind, lg.get("stat", {}))
            lines.append(
                f'<div class="head"{margin}><span class="date">{d}</span>'
                f'<span class="vs">vs {opp} ({label})</span></div>'
            )
            lines.append(f'<div class="line">{line}</div>')
    else:
        # 通常: 適切な1試合
        if p["is_pitcher"] and has_pit:
            kind, lg = "pitching", last_game["pitching"]
        elif p["is_hitter"] and has_hit:
            kind, lg = "hitting", last_game["hitting"]
        elif has_pit:
            kind, lg = "pitching", last_game["pitching"]
        else:
            kind, lg = "hitting", last_game["hitting"]
        d = fmt_jp_date(lg.get("date", ""))
        opp = team_code(lg.get("opp", ""))
        line = render_stat_line(kind, lg.get("stat", {}))
        lines.append(
            f'<div class="head"><span class="date">{d}</span>'
            f'<span class="vs">vs {opp}</span></div>'
        )
        lines.append(f'<div class="line">{line}</div>')

    inner = "\n            ".join(lines)
    return f"""          <div class="last-game">
            {inner}
          </div>"""


def render_video_block(highlight: dict[str, Any] | None) -> str:
    if not highlight:
        return ""
    title = html_mod.escape(highlight.get("title", ""))
    # 試合日を優先表示（無ければハイライト公開日にフォールバック）
    short = fmt_short_date(highlight.get("game_date") or highlight.get("date", ""))

    # SpoTVnow YouTube
    if highlight.get("source") == "youtube" and highlight.get("videoId"):
        vid = html_mod.escape(highlight["videoId"])
        return f"""          <div class="video">
            <iframe src="https://www.youtube.com/embed/{vid}"
                    title="{title}"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                    allowfullscreen loading="lazy" referrerpolicy="strict-origin-when-cross-origin"></iframe>
            <div class="video-caption">▶ {title} ({short}・SpoTVnow)</div>
          </div>"""

    # MLB公式動画（フォールバック）
    if not highlight.get("mp4"):
        return ""
    thumb = html_mod.escape(highlight.get("thumb", ""))
    mp4 = html_mod.escape(highlight["mp4"])
    return f"""          <div class="video">
            <video controls preload="none" playsinline poster="{thumb}">
              <source src="{mp4}" type="video/mp4">
            </video>
            <div class="video-caption">▶ {title} ({short}・試合のハイライト)</div>
          </div>"""


def render_card(p: dict[str, Any], stats_entry: dict[str, Any],
                highlight: dict[str, Any] | None) -> str:
    season = stats_entry.get("season", {})
    last_game = stats_entry.get("lastGame", {})
    has_data = bool(season) or bool(last_game)

    name_ja = html_mod.escape(p["name_ja"])

    if not has_data:
        body_inner = '          <div class="empty-msg">2026年 出場記録なし</div>'
    else:
        blocks: list[str] = []
        if "hitting" in season and p["is_hitter"]:
            blocks.append(render_batting_block(season["hitting"]))
        if "pitching" in season and p["is_pitcher"]:
            blocks.append(render_pitching_block(season["pitching"],
                                                with_top_margin=bool(blocks)))
        season_section = ""
        if blocks:
            season_section = "          <div>\n" + "\n".join(blocks) + "\n          </div>"
        last_game_section = render_last_game(p, last_game)
        video_section = render_video_block(highlight)
        body_inner = "\n\n".join(s for s in (season_section, last_game_section, video_section) if s)

    return f"""      <article class="player" data-team="{p['team_class']}">
        <div class="avatar" data-num="{p['jersey']}">
          <span class="team-bar"><span class="swatch"></span>{p['team_code']}</span>
          <img src="images/{p['key']}.jpg" alt="{name_ja}" onerror="this.remove()">
        </div>
        <div class="body">
          <div class="name-row">
            <div>
              <div class="name">{name_ja}<span class="num">#{p['jersey']}</span></div>
              <div class="team-name">{p['team_full']} · {p['position']}</div>
            </div>
          </div>

{body_inner}
        </div>
      </article>"""


# CSS は元のHTMLと完全に同じものを保持
CSS = """  :root {
    --bg: #f6f7fb;
    --bg-soft: #eef1f7;
    --card: #ffffff;
    --border: rgba(15, 23, 42, 0.08);
    --border-strong: rgba(15, 23, 42, 0.16);
    --text: #0f172a;
    --text-dim: #5b6478;
    --text-faint: #8b94a8;
    --accent: #2563eb;
    --accent-2: #7c3aed;
    --accent-3: #ec4899;
    --gold: #d97706;
    --green: #059669;
    --red: #dc2626;

    --dodgers-1: #1e64c8;  --dodgers-2: #0a3b8a;
    --cubs-1: #cc3433;     --cubs-2: #0e3386;
    --redsox-1: #bd3039;   --redsox-2: #0c2340;
    --padres-1: #ffc425;   --padres-2: #2f241d;
    --whitesox-1: #27251F; --whitesox-2: #4a4a4a;
    --bluejays-1: #134A8E; --bluejays-2: #1D2D5C;
    --neutral-1: #475569;  --neutral-2: #1e293b;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    color: var(--text);
    font-family: "Inter", "Noto Sans JP", -apple-system, BlinkMacSystemFont,
                 "Segoe UI", "Hiragino Sans", "Yu Gothic UI", "Meiryo", sans-serif;
    line-height: 1.65;
    background:
      radial-gradient(1000px 500px at 100% -10%, rgba(124, 58, 237, 0.06), transparent 60%),
      radial-gradient(900px 500px at 0% 110%, rgba(37, 99, 235, 0.07), transparent 60%),
      var(--bg);
    background-attachment: fixed;
    min-height: 100vh;
  }

  /* ===== ヘッダー ===== */
  header.site {
    position: relative;
    padding: 56px 20px 36px;
    text-align: center;
  }
  header.site::after {
    content: ""; position: absolute; left: 50%; bottom: 0; transform: translateX(-50%);
    width: 70%; max-width: 720px; height: 1px;
    background: linear-gradient(90deg, transparent, var(--border-strong), transparent);
  }
  .eyebrow {
    display: inline-flex; align-items: center; gap: 10px;
    padding: 6px 14px; border-radius: 999px;
    background: rgba(37, 99, 235, 0.08);
    border: 1px solid rgba(37, 99, 235, 0.2);
    color: var(--accent);
    font-size: 0.72rem; letter-spacing: 0.18em; text-transform: uppercase;
    margin-bottom: 18px; font-weight: 600;
  }
  .eyebrow .dot {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 12px rgba(5, 150, 105, 0.6);
    animation: pulse 1.8s ease-in-out infinite;
  }
  @keyframes pulse {
    0%,100% { opacity: 1; transform: scale(1); }
    50%     { opacity: 0.4; transform: scale(0.8); }
  }
  header.site h1 {
    margin: 0;
    font-family: "Bebas Neue", "Noto Sans JP", sans-serif;
    font-size: clamp(2.4rem, 6vw, 4rem);
    letter-spacing: 0.04em; line-height: 1.05;
    background: linear-gradient(135deg, #0f172a 0%, #2563eb 60%, #7c3aed 100%);
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  header.site h1 .ball { display: inline-block; transform: translateY(-4px); margin-right: 6px; -webkit-text-fill-color: initial; }
  header.site .subtitle { margin-top: 8px; color: var(--text-dim); font-size: 0.95rem; letter-spacing: 0.05em; }
  .date-block {
    margin-top: 22px;
    display: inline-flex; align-items: baseline; gap: 14px;
    padding: 14px 22px; border-radius: 14px;
    background: var(--card); border: 1px solid var(--border);
    box-shadow: 0 6px 20px -10px rgba(15, 23, 42, 0.15);
  }
  .date-block .date {
    font-family: "Bebas Neue", sans-serif;
    font-size: 1.6rem; letter-spacing: 0.06em;
    background: linear-gradient(135deg, var(--accent), var(--accent-3));
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .date-block .updated { color: var(--text-faint); font-size: 0.78rem; }

  /* ===== メイン ===== */
  main {
    max-width: 1080px;
    margin: 0 auto;
    padding: 28px 20px 40px;
    display: grid; gap: 22px;
  }

  /* セクション見出し */
  .section-title {
    display: flex; align-items: center; gap: 12px;
    margin: 8px 4px 0;
    color: var(--text-faint);
    font-size: 0.78rem; letter-spacing: 0.22em; text-transform: uppercase; font-weight: 600;
  }
  .section-title::before, .section-title::after {
    content: ""; flex: 1; height: 1px;
    background: linear-gradient(90deg, transparent, var(--border-strong), transparent);
  }

  /* ===== 選手カード ===== */
  .player-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 18px;
  }
  .player {
    position: relative;
    display: flex; flex-direction: column;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 18px;
    overflow: hidden;
    transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease;
    animation: fadeUp 0.6s ease both;
    box-shadow: 0 6px 20px -14px rgba(15, 23, 42, 0.2);
  }
  .player:hover {
    transform: translateY(-4px); border-color: var(--border-strong);
    box-shadow: 0 18px 40px -18px rgba(15, 23, 42, 0.3);
  }

  /* ヘッドショット */
  .avatar {
    position: relative; width: 100%;
    aspect-ratio: 16 / 11;
    background:
      radial-gradient(circle at 30% 20%, rgba(255,255,255,0.18), transparent 50%),
      linear-gradient(135deg, var(--team-1, #475569), var(--team-2, #1e293b));
    display: grid; place-items: center; overflow: hidden;
  }
  .avatar::before {
    content: attr(data-num);
    font-family: "Bebas Neue", sans-serif;
    font-size: clamp(5rem, 14vw, 7rem); line-height: 1;
    color: rgba(255, 255, 255, 0.92);
    text-shadow: 0 8px 30px rgba(0, 0, 0, 0.35);
    z-index: 1;
  }
  .avatar::after {
    content: ""; position: absolute; inset: 0;
    background: repeating-linear-gradient(135deg, transparent 0 24px, rgba(255,255,255,0.04) 24px 25px);
    pointer-events: none;
  }
  .avatar img {
    position: absolute; inset: 0; width: 100%; height: 100%;
    object-fit: cover; object-position: center 25%;
    z-index: 2;
  }
  .team-bar {
    position: absolute; top: 12px; left: 12px; z-index: 3;
    display: flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: 999px;
    background: rgba(15, 23, 42, 0.6); color: #fff;
    font-size: 0.65rem; letter-spacing: 0.14em; font-weight: 600;
    backdrop-filter: blur(6px);
  }
  .team-bar .swatch {
    width: 8px; height: 8px; border-radius: 50%;
    background: var(--team-1);
    box-shadow: 0 0 0 1px rgba(255,255,255,0.5);
  }

  /* 本文 */
  .body {
    padding: 16px 18px 18px;
    display: flex; flex-direction: column; gap: 12px;
  }
  .name-row {
    display: flex; justify-content: space-between; align-items: flex-start; gap: 8px;
  }
  .name { font-weight: 800; font-size: 1.15rem; letter-spacing: 0.01em; }
  .name .num {
    font-family: "Bebas Neue", sans-serif; font-size: 0.95rem;
    color: var(--text-faint); margin-left: 6px; letter-spacing: 0.06em;
  }
  .team-name { font-size: 0.7rem; color: var(--text-faint); letter-spacing: 0.12em; font-weight: 600; }

  /* 統計 */
  .block-label {
    font-size: 0.68rem; letter-spacing: 0.18em; text-transform: uppercase;
    color: var(--text-faint); font-weight: 700;
    margin-bottom: 6px;
  }
  .stat-grid {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px;
    background: var(--bg-soft);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 8px;
  }
  .stat-grid + .stat-grid { margin-top: 6px; }
  .stat-grid .cell { text-align: center; }
  .stat-grid .num {
    display: block;
    font-family: "Bebas Neue", sans-serif;
    font-size: 1.35rem; line-height: 1;
    color: var(--text); letter-spacing: 0.02em;
  }
  .stat-grid .lbl {
    display: block;
    font-size: 0.62rem; letter-spacing: 0.12em;
    color: var(--text-faint); margin-top: 4px; font-weight: 600;
  }
  .stat-grid.pit .num { color: var(--accent-2); }

  /* 直近の試合 */
  .last-game {
    border-top: 1px dashed var(--border);
    padding-top: 10px;
  }
  .last-game .head {
    display: flex; justify-content: space-between; align-items: baseline;
    margin-bottom: 4px;
  }
  .last-game .date {
    font-family: "Bebas Neue", sans-serif; font-size: 1rem;
    color: var(--text); letter-spacing: 0.04em;
  }
  .last-game .vs { font-size: 0.78rem; color: var(--text-dim); }
  .last-game .line {
    font-size: 0.85rem; color: var(--text-dim);
    font-variant-numeric: tabular-nums;
  }
  .last-game .line strong { color: var(--text); font-weight: 700; }
  .last-game .line + .line { margin-top: 2px; }

  /* 動画 */
  .video {
    margin-top: 4px;
    border-radius: 12px; overflow: hidden;
    background: #000;
    border: 1px solid var(--border);
  }
  .video video,
  .video iframe {
    display: block; width: 100%; aspect-ratio: 16/9; background: #000; border: 0;
  }
  .video-caption {
    font-size: 0.74rem; color: var(--text-dim);
    padding: 8px 10px; background: var(--bg-soft);
    border-top: 1px solid var(--border);
    line-height: 1.4;
  }

  .empty-msg {
    background: var(--bg-soft);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px;
    color: var(--text-dim);
    font-size: 0.85rem;
    text-align: center;
  }

  /* チーム別カラー */
  .player[data-team="dodgers"]  { --team-1: var(--dodgers-1);  --team-2: var(--dodgers-2); }
  .player[data-team="cubs"]     { --team-1: var(--cubs-1);     --team-2: var(--cubs-2); }
  .player[data-team="redsox"]   { --team-1: var(--redsox-1);   --team-2: var(--redsox-2); }
  .player[data-team="padres"]   { --team-1: var(--padres-1);   --team-2: var(--padres-2); }
  .player[data-team="whitesox"] { --team-1: var(--whitesox-1); --team-2: var(--whitesox-2); }
  .player[data-team="bluejays"] { --team-1: var(--bluejays-1); --team-2: var(--bluejays-2); }

  /* アニメ遅延 */
  .player:nth-child(1) { animation-delay: 0.05s; }
  .player:nth-child(2) { animation-delay: 0.10s; }
  .player:nth-child(3) { animation-delay: 0.15s; }
  .player:nth-child(4) { animation-delay: 0.20s; }
  .player:nth-child(5) { animation-delay: 0.25s; }
  .player:nth-child(6) { animation-delay: 0.30s; }
  .player:nth-child(7) { animation-delay: 0.35s; }
  .player:nth-child(8) { animation-delay: 0.40s; }
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(14px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  footer {
    text-align: center; color: var(--text-faint);
    font-size: 0.75rem; padding: 30px 16px 50px; letter-spacing: 0.05em;
  }
  footer a { color: var(--accent); text-decoration: none; border-bottom: 1px dashed rgba(37,99,235,0.4); }
  footer a:hover { color: var(--accent-2); border-color: var(--accent-2); }"""


def render_html(stats: list[dict[str, Any]],
                highlights: dict[str, dict[str, Any]],
                target_date: datetime) -> str:
    target_label = fmt_us_date_caps(target_date)
    today_label = fmt_us_date(datetime.now(tz=JST))

    stats_by_key = {s["key"]: s for s in stats}
    cards_html = "\n\n".join(
        render_card(p, stats_by_key.get(p["key"], {}), highlights.get(p["key"]))
        for p in PLAYERS
    )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="googlebot" content="noindex, nofollow">
<title>MLB日本人選手 前日成績</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;600;800&family=Noto+Sans+JP:wght@400;600;800&display=swap" rel="stylesheet">
<style>
{CSS}
</style>
</head>
<body>
  <header class="site">
    <span class="eyebrow"><span class="dot"></span>DAILY REPORT</span>
    <h1><span class="ball">⚾</span>JAPANESE IN MLB</h1>
    <div class="subtitle">2026シーズンの日本人選手 成績ダッシュボード</div>
    <div class="date-block">
      <div class="date">{target_label}</div>
      <div class="updated">取得 / {today_label}</div>
    </div>
  </header>

  <main>
    <div class="section-title">Roster &amp; Latest Stats</div>

    <div class="player-grid">

{cards_html}

    </div>
  </main>

  <footer>
    Data: <a href="https://statsapi.mlb.com" target="_blank" rel="noopener">MLB Stats API</a> ·
    Video: <a href="https://www.mlb.com" target="_blank" rel="noopener">MLB.com</a>
  </footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    target = datetime.now(tz=JST) - timedelta(days=1)
    print(f"[INFO] Target date (JST yesterday): {target.strftime('%Y-%m-%d')}",
          file=sys.stderr)

    try:
        stats, highlights = collect_data()
    except requests.RequestException as e:
        print(f"[ERROR] API failure, keeping previous output: {e}", file=sys.stderr)
        return 1

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(render_html(stats, highlights, target), encoding="utf-8")
    print(f"[DONE] Wrote {OUTPUT_HTML}", file=sys.stderr)

    OUTPUT_STATS_JSON.write_text(
        json.dumps(stats, ensure_ascii=False, indent=4), encoding="utf-8")
    OUTPUT_HIGHLIGHTS_JSON.write_text(
        json.dumps(highlights, ensure_ascii=False, indent=4), encoding="utf-8")
    print(f"[DONE] Wrote {OUTPUT_STATS_JSON.name} and {OUTPUT_HIGHLIGHTS_JSON.name}",
          file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
