"""
MLB日本人選手 前日成績取得スクリプト

MLB Stats API (https://statsapi.mlb.com/api/v1) から
対象選手の前日試合成績を取得し、docs/index.html を生成する。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

API_BASE = "https://statsapi.mlb.com/api/v1"
JST = timezone(timedelta(hours=9))

# 対象選手（仕様書記載の7名）
# personId は MLB Stats API の /people/search で確認した固定ID。
# 万一IDが変わった場合のためにフルネーム(英)も保持。
TARGET_PLAYERS: list[dict[str, Any]] = [
    {"id": 660271, "name_ja": "大谷翔平",   "name_en": "Shohei Ohtani"},
    {"id": 680781, "name_ja": "山本由伸",   "name_en": "Yoshinobu Yamamoto"},
    {"id": 684007, "name_ja": "今永昇太",   "name_en": "Shota Imanaga"},
    {"id": 673548, "name_ja": "鈴木誠也",   "name_en": "Seiya Suzuki"},
    {"id": 676664, "name_ja": "吉田正尚",   "name_en": "Masataka Yoshida"},
    {"id": 684006, "name_ja": "上沢直之",   "name_en": "Naoyuki Uwasawa"},
    {"id": 670242, "name_ja": "松井裕樹",   "name_en": "Yuki Matsui"},
]

OUTPUT_HTML = Path(__file__).resolve().parent.parent / "docs" / "index.html"
REQUEST_TIMEOUT = 20


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------

@dataclass
class PlayerCard:
    name_ja: str
    team: str
    position: str
    opponent: str
    is_home: bool
    game_status: str  # "Final", "Postponed", etc.
    # 打撃
    batting: dict[str, Any] | None = None
    season_batting: dict[str, Any] | None = None
    # 投手
    pitching: dict[str, Any] | None = None
    season_pitching: dict[str, Any] | None = None
    # 結果フラグ
    decision: str = ""  # "W", "L", "S", "H" など


# ---------------------------------------------------------------------------
# API 呼び出し
# ---------------------------------------------------------------------------

def get_yesterday_jst() -> datetime:
    """JSTでの『昨日』を返す。MLBの試合日付に対応。"""
    now_jst = datetime.now(tz=JST)
    return now_jst - timedelta(days=1)


def fetch_schedule(date_str: str) -> list[dict[str, Any]]:
    """指定日のMLBスケジュールを取得する。"""
    url = f"{API_BASE}/schedule"
    params = {"sportId": 1, "date": date_str, "hydrate": "team"}
    res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    data = res.json()
    games: list[dict[str, Any]] = []
    for d in data.get("dates", []):
        games.extend(d.get("games", []))
    return games


def fetch_boxscore(game_pk: int) -> dict[str, Any]:
    """boxscoreを取得。"""
    url = f"{API_BASE}/game/{game_pk}/boxscore"
    res = requests.get(url, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    return res.json()


def fetch_player_season_stats(player_id: int, group: str, season: int) -> dict[str, Any]:
    """選手の今季通算成績を取得 (group='hitting' or 'pitching')。"""
    url = f"{API_BASE}/people/{player_id}/stats"
    params = {"stats": "season", "group": group, "season": season}
    try:
        res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
        data = res.json()
        for s in data.get("stats", []):
            splits = s.get("splits", [])
            if splits:
                return splits[0].get("stat", {})
    except requests.RequestException:
        pass
    return {}


# ---------------------------------------------------------------------------
# データ抽出
# ---------------------------------------------------------------------------

def find_player_in_boxscore(
    boxscore: dict[str, Any], player_id: int
) -> tuple[dict[str, Any] | None, str, str, bool]:
    """
    boxscoreから対象選手を探す。
    戻り値: (player_data, team_name, position, is_home)
    """
    teams = boxscore.get("teams", {})
    for side in ("home", "away"):
        team = teams.get(side, {})
        players = team.get("players", {})
        key = f"ID{player_id}"
        if key in players:
            p = players[key]
            team_name = team.get("team", {}).get("name", "")
            pos = p.get("position", {}).get("abbreviation", "")
            return p, team_name, pos, side == "home"
    return None, "", "", False


def extract_batting(player_data: dict[str, Any]) -> dict[str, Any] | None:
    """boxscore選手データから打撃成績を抽出。打席に立っていなければNone。"""
    batting = player_data.get("stats", {}).get("batting", {})
    if not batting:
        return None
    at_bats = batting.get("atBats", 0)
    plate = batting.get("plateAppearances", 0)
    if at_bats == 0 and plate == 0:
        return None
    return {
        "atBats": at_bats,
        "hits": batting.get("hits", 0),
        "homeRuns": batting.get("homeRuns", 0),
        "rbi": batting.get("rbi", 0),
        "runs": batting.get("runs", 0),
        "baseOnBalls": batting.get("baseOnBalls", 0),
        "strikeOuts": batting.get("strikeOuts", 0),
        "stolenBases": batting.get("stolenBases", 0),
    }


def extract_pitching(player_data: dict[str, Any]) -> dict[str, Any] | None:
    """boxscore選手データから投手成績を抽出。登板していなければNone。"""
    pitching = player_data.get("stats", {}).get("pitching", {})
    if not pitching:
        return None
    ip = pitching.get("inningsPitched")
    if not ip or ip == "0.0":
        return None
    note = pitching.get("note", "") or ""
    decision = ""
    if "(W" in note:
        decision = "W"
    elif "(L" in note:
        decision = "L"
    elif "(S" in note:
        decision = "S"
    elif "(H" in note:
        decision = "H"
    elif "(BS" in note:
        decision = "BS"
    return {
        "inningsPitched": ip,
        "strikeOuts": pitching.get("strikeOuts", 0),
        "baseOnBalls": pitching.get("baseOnBalls", 0),
        "hits": pitching.get("hits", 0),
        "runs": pitching.get("runs", 0),
        "earnedRuns": pitching.get("earnedRuns", 0),
        "homeRuns": pitching.get("homeRuns", 0),
        "decision": decision,
    }


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def collect_player_cards(target_date: datetime) -> list[PlayerCard]:
    date_str = target_date.strftime("%Y-%m-%d")
    season = target_date.year

    print(f"[INFO] Target date (JST yesterday): {date_str}", file=sys.stderr)

    games = fetch_schedule(date_str)
    print(f"[INFO] {len(games)} games found", file=sys.stderr)

    cards: list[PlayerCard] = []

    for player in TARGET_PLAYERS:
        pid = player["id"]
        name_ja = player["name_ja"]
        found_card: PlayerCard | None = None

        for game in games:
            game_pk = game.get("gamePk")
            status = game.get("status", {}).get("detailedState", "")
            abstract = game.get("status", {}).get("abstractGameState", "")

            if not game_pk:
                continue

            # 試合に登録されている選手か確認するため boxscore を取得
            try:
                box = fetch_boxscore(game_pk)
            except requests.RequestException as e:
                print(f"[WARN] boxscore fetch failed game={game_pk}: {e}", file=sys.stderr)
                continue

            pdata, team_name, pos, is_home = find_player_in_boxscore(box, pid)
            if pdata is None:
                continue

            # 対戦相手
            teams_info = game.get("teams", {})
            if is_home:
                opponent = teams_info.get("away", {}).get("team", {}).get("name", "")
            else:
                opponent = teams_info.get("home", {}).get("team", {}).get("name", "")

            # 試合中止
            if status in ("Postponed", "Cancelled") or "Postponed" in status:
                # 試合自体がないので非表示扱い（仕様: 試合なし非表示）
                print(f"[INFO] {name_ja}: game postponed/cancelled", file=sys.stderr)
                break

            # 試合がまだ終わっていない場合（Live/Preview）はスキップ
            if abstract != "Final":
                print(f"[INFO] {name_ja}: game not final ({abstract})", file=sys.stderr)
                break

            batting = extract_batting(pdata)
            pitching = extract_pitching(pdata)

            if batting is None and pitching is None:
                # ロースター登録だけで出場していない → 非表示
                print(f"[INFO] {name_ja}: no appearance", file=sys.stderr)
                break

            season_batting = (
                fetch_player_season_stats(pid, "hitting", season) if batting else None
            )
            season_pitching = (
                fetch_player_season_stats(pid, "pitching", season) if pitching else None
            )

            found_card = PlayerCard(
                name_ja=name_ja,
                team=team_name,
                position=pos,
                opponent=opponent,
                is_home=is_home,
                game_status=status,
                batting=batting,
                season_batting=season_batting,
                pitching=pitching,
                season_pitching=season_pitching,
                decision=pitching.get("decision", "") if pitching else "",
            )
            break

        if found_card:
            cards.append(found_card)
            print(f"[OK] {name_ja} card created", file=sys.stderr)

    return cards


# ---------------------------------------------------------------------------
# HTML 生成
# ---------------------------------------------------------------------------

def render_card(card: PlayerCard) -> str:
    rows: list[str] = []

    vs_text = f"{'vs' if card.is_home else '@'} {card.opponent}"
    decision_badge = ""
    if card.decision:
        label_map = {"W": "勝", "L": "敗", "S": "S", "H": "H", "BS": "BS"}
        cls = "win" if card.decision == "W" else "loss" if card.decision == "L" else "save"
        decision_badge = f'<span class="badge {cls}">{label_map.get(card.decision, card.decision)}</span>'

    if card.pitching:
        p = card.pitching
        sp = card.season_pitching or {}
        era = sp.get("era", "-")
        rows.append(f"""
        <div class="stat-row">
          <span class="stat-label">投球回</span><span class="stat-value">{p['inningsPitched']}</span>
          <span class="stat-label">奪三振</span><span class="stat-value">{p['strikeOuts']}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">与四球</span><span class="stat-value">{p['baseOnBalls']}</span>
          <span class="stat-label">被安打</span><span class="stat-value">{p['hits']}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">失点</span><span class="stat-value">{p['runs']}</span>
          <span class="stat-label">自責点</span><span class="stat-value">{p['earnedRuns']}</span>
        </div>
        <div class="season">今季 防御率 <strong>{era}</strong></div>
        """)

    if card.batting:
        b = card.batting
        sb = card.season_batting or {}
        avg = sb.get("avg", "-")
        obp = sb.get("obp", "-")
        slg = sb.get("slg", "-")
        rows.append(f"""
        <div class="stat-row">
          <span class="stat-label">打数</span><span class="stat-value">{b['atBats']}</span>
          <span class="stat-label">安打</span><span class="stat-value">{b['hits']}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">本塁打</span><span class="stat-value">{b['homeRuns']}</span>
          <span class="stat-label">打点</span><span class="stat-value">{b['rbi']}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">得点</span><span class="stat-value">{b['runs']}</span>
          <span class="stat-label">四球</span><span class="stat-value">{b['baseOnBalls']}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">三振</span><span class="stat-value">{b['strikeOuts']}</span>
          <span class="stat-label">盗塁</span><span class="stat-value">{b['stolenBases']}</span>
        </div>
        <div class="season">今季 打率 <strong>{avg}</strong> / 出塁 <strong>{obp}</strong> / 長打 <strong>{slg}</strong></div>
        """)

    inner = "\n".join(rows)
    return f"""
    <article class="card">
      <header class="card-head">
        <h2>{card.name_ja} {decision_badge}</h2>
        <div class="meta">{card.team}・{card.position}</div>
        <div class="opp">{vs_text}</div>
      </header>
      <div class="card-body">
        {inner}
      </div>
    </article>
    """


def render_html(cards: list[PlayerCard], target_date: datetime) -> str:
    updated = datetime.now(tz=JST).strftime("%Y年%m月%d日 %H:%M 更新")
    target_label = target_date.strftime("%Y年%m月%d日")

    if cards:
        cards_html = "\n".join(render_card(c) for c in cards)
    else:
        cards_html = '<p class="empty">本日対象の試合・出場選手はいません。</p>'

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MLB日本人選手 前日成績</title>
<style>
  :root {{
    --bg: #0d1117;
    --bg-card: #161b22;
    --bg-card-hover: #1c2330;
    --border: #30363d;
    --text: #e6edf3;
    --text-dim: #8b949e;
    --accent: #58a6ff;
    --win: #3fb950;
    --loss: #f85149;
    --save: #d29922;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans",
                 "Yu Gothic UI", "Meiryo", sans-serif;
    line-height: 1.6;
  }}
  header.site {{
    padding: 24px 16px 16px;
    text-align: center;
    border-bottom: 1px solid var(--border);
  }}
  header.site h1 {{
    margin: 0 0 4px;
    font-size: 1.4rem;
    letter-spacing: 0.02em;
  }}
  header.site .date {{
    color: var(--accent);
    font-weight: 600;
  }}
  header.site .updated {{
    color: var(--text-dim);
    font-size: 0.8rem;
    margin-top: 4px;
  }}
  main {{
    max-width: 720px;
    margin: 0 auto;
    padding: 16px;
    display: grid;
    gap: 14px;
  }}
  .card {{
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    transition: background 0.2s;
  }}
  .card:hover {{ background: var(--bg-card-hover); }}
  .card-head h2 {{
    margin: 0 0 4px;
    font-size: 1.15rem;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .meta {{ color: var(--text-dim); font-size: 0.85rem; }}
  .opp {{ color: var(--accent); font-size: 0.95rem; margin-top: 2px; }}
  .card-body {{
    margin-top: 12px;
    border-top: 1px solid var(--border);
    padding-top: 12px;
  }}
  .stat-row {{
    display: grid;
    grid-template-columns: auto 1fr auto 1fr;
    gap: 6px 10px;
    align-items: baseline;
    padding: 4px 0;
  }}
  .stat-label {{ color: var(--text-dim); font-size: 0.85rem; }}
  .stat-value {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
  .season {{
    margin-top: 8px;
    padding-top: 8px;
    border-top: 1px dashed var(--border);
    color: var(--text-dim);
    font-size: 0.85rem;
  }}
  .season strong {{ color: var(--text); }}
  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 700;
  }}
  .badge.win {{ background: var(--win); color: #061a0a; }}
  .badge.loss {{ background: var(--loss); color: #1a0606; }}
  .badge.save {{ background: var(--save); color: #1a1306; }}
  .empty {{
    text-align: center;
    color: var(--text-dim);
    padding: 32px 16px;
  }}
  footer {{
    text-align: center;
    color: var(--text-dim);
    font-size: 0.75rem;
    padding: 24px 16px 32px;
  }}
  footer a {{ color: var(--accent); text-decoration: none; }}
  @media (max-width: 480px) {{
    .stat-row {{ grid-template-columns: auto 1fr auto 1fr; gap: 4px 8px; }}
    .card {{ padding: 14px; }}
  }}
</style>
</head>
<body>
  <header class="site">
    <h1>⚾ MLB日本人選手 前日の成績</h1>
    <div class="date">{target_label}</div>
    <div class="updated">{updated}</div>
  </header>
  <main>
    {cards_html}
  </main>
  <footer>
    Data: <a href="https://statsapi.mlb.com" target="_blank" rel="noopener">MLB Stats API</a>
  </footer>
</body>
</html>
"""


def main() -> int:
    target = get_yesterday_jst()
    try:
        cards = collect_player_cards(target)
    except requests.RequestException as e:
        # 仕様: API失敗時は前回HTMLを維持（上書きしない）
        print(f"[ERROR] API failure, keeping previous HTML: {e}", file=sys.stderr)
        return 1

    html = render_html(cards, target)
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"[DONE] Wrote {OUTPUT_HTML} ({len(cards)} cards)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
