#!/usr/bin/env python3
"""今日の天文学（APOD: Astronomy Picture of the Day）を取得し、
高校生が理解できるレベルの日本語にまとめて Slack の #天文学 へ投稿する。"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from slack_sdk import WebClient

JST = timezone(timedelta(hours=9))

DATA_FILE = Path(__file__).parent.parent / "data" / "apod_seen.json"
SLACK_CHANNEL = "C0BSUECLM1P"  # #天文学
APOD_ENDPOINT = "https://api.nasa.gov/planetary/apod"
SUMMARY_LENGTH = 350  # 要約の目安文字数


def today_jst() -> str:
    return datetime.now(JST).date().isoformat()


def load_state() -> dict:
    """{"last_apod_date": "YYYY-MM-DD", "last_posted": "YYYY-MM-DD"} を返す。"""
    if not DATA_FILE.exists():
        return {}
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def save_state(apod_date: str) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(
            {"last_apod_date": apod_date, "last_posted": today_jst()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def fetch_apod(api_key: str) -> dict:
    """最新の APOD を取得する。

    日付は指定せず「今の時点での最新 1 件」を取る。APOD は米国東部時間の 0 時
    （= 13:00 JST / 冬時間は 14:00 JST）に更新されるため、更新前に走った回は
    前日ぶんを取得することになるが、その場合は呼び出し側の重複ガードで投稿しない。
    """
    resp = requests.get(
        APOD_ENDPOINT,
        params={"api_key": api_key, "thumbs": "true"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def apod_page_url(apod_date: str) -> str:
    """APOD の公式ページ URL（https://apod.nasa.gov/apod/apYYMMDD.html）を組み立てる。"""
    try:
        d = datetime.strptime(apod_date, "%Y-%m-%d")
    except ValueError:
        return "https://apod.nasa.gov/apod/astropix.html"
    return f"https://apod.nasa.gov/apod/ap{d.strftime('%y%m%d')}.html"


def _extract_json(text: str) -> dict | None:
    """モデル出力から JSON オブジェクトを取り出す（```json フェンス付きにも対応）。"""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        candidate = text[start : end + 1] if start != -1 and end > start else None
    if candidate is None:
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def summarize(client, apod: dict) -> dict:
    """Claude（Haiku）で高校生向けの日本語まとめを生成する。

    戻り値: {"title_ja": str, "summary": str, "glossary": [{"term", "desc"}], "point": str}
    失敗時は英語原文の冒頭で代替する。
    """
    explanation = " ".join((apod.get("explanation") or "").split())
    fallback = {
        "title_ja": "",
        "summary": explanation[:600],
        "glossary": [],
        "point": "",
    }
    if client is None or not explanation:
        return fallback

    import anthropic

    prompt = (
        "あなたは高校生向けの科学解説者です。以下は NASA の "
        "APOD（Astronomy Picture of the Day）の英語解説文です。"
        "日本の高校生（物理・地学の授業を受けた程度）が読んで理解できる日本語にまとめてください。\n\n"
        "条件:\n"
        f"- summary は日本語で約{SUMMARY_LENGTH}字（±50字）。何が写っているか→なぜ面白いか→"
        "わかっていること／いないこと、の順で説明する\n"
        "- 数値や固有名詞は原文の内容を守り、勝手に事実を足さない\n"
        "- 専門用語は使ってよいが、glossary で1つ25〜50字でかみくだいて説明する（0〜4個）\n"
        "- title_ja は原題の日本語訳（20字程度）\n"
        "- point は「ここが面白い」を40字以内で1文\n"
        "- 出力は次のキーを持つ JSON オブジェクトのみ。前置き・コードフェンスは不要\n"
        '  {"title_ja": "...", "summary": "...", '
        '"glossary": [{"term": "...", "desc": "..."}], "point": "..."}\n\n'
        f"原題: {apod.get('title', '')}\n\n解説文:\n{explanation}"
    )
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
    except anthropic.APIStatusError as e:
        print(f"  要約APIエラー ({e.status_code}): 原文で代替します", file=sys.stderr)
        return fallback
    except anthropic.APIConnectionError:
        print("  要約API接続エラー: 原文で代替します", file=sys.stderr)
        return fallback
    except Exception as e:
        print(f"  要約失敗 ({e}): 原文で代替します", file=sys.stderr)
        return fallback

    parsed = _extract_json(text)
    if parsed is None or not parsed.get("summary"):
        print("  要約のJSON解析に失敗: 生テキストを使います", file=sys.stderr)
        return {**fallback, "summary": text.strip() or fallback["summary"]}

    glossary = [
        g
        for g in (parsed.get("glossary") or [])
        if isinstance(g, dict) and g.get("term") and g.get("desc")
    ]
    return {
        "title_ja": str(parsed.get("title_ja") or "").strip(),
        "summary": str(parsed["summary"]).strip(),
        "glossary": glossary[:4],
        "point": str(parsed.get("point") or "").strip(),
    }


def format_date_ja(apod_date: str) -> str:
    """APOD の日付（YYYY-MM-DD）を「YYYY年MM月DD日」にする。解析できなければ JST の今日。"""
    try:
        return datetime.strptime(apod_date, "%Y-%m-%d").strftime("%Y年%m月%d日")
    except ValueError:
        return datetime.now(JST).strftime("%Y年%m月%d日")


def build_blocks(apod: dict, digest: dict) -> list[dict]:
    apod_date = apod.get("date", "")
    posted_on = format_date_ja(apod_date)
    title_en = apod.get("title", "(no title)")
    title_ja = digest.get("title_ja")
    page_url = apod_page_url(apod_date)

    heading = f"*<{page_url}|{title_ja or title_en}>*"
    if title_ja:
        heading += f"\n原題: {title_en}"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🔭 今日の天文学（{posted_on}）",
                "emoji": True,
            },
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": heading}},
    ]

    # 画像（動画の場合は thumbs=true で得たサムネイル）を貼る
    media_type = apod.get("media_type")
    image_url = apod.get("url") if media_type == "image" else apod.get("thumbnail_url")
    if image_url:
        blocks.append(
            {
                "type": "image",
                "image_url": image_url,
                "alt_text": title_en[:150],
            }
        )
    if media_type == "video" and apod.get("url"):
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"🎬 <{apod['url']}|動画を見る>"},
            }
        )

    blocks.append(
        {"type": "section", "text": {"type": "mrkdwn", "text": digest["summary"]}}
    )

    if digest.get("point"):
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"✨ *ここが面白い*\n{digest['point']}"},
            }
        )

    if digest.get("glossary"):
        terms = "\n".join(f"• *{g['term']}* — {g['desc']}" for g in digest["glossary"])
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"📖 *ことばのメモ*\n{terms}"},
            }
        )

    credit = apod.get("copyright")
    context = f"出典: <{page_url}|NASA APOD {apod_date}>"
    if credit:
        context += f" ／ Credit: {' '.join(credit.split())}"
    blocks.append(
        {"type": "context", "elements": [{"type": "mrkdwn", "text": context}]}
    )
    return blocks


def main() -> None:
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        print("SLACK_BOT_TOKEN が設定されていません", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("NASA_API_KEY", "").strip() or "DEMO_KEY"
    if api_key == "DEMO_KEY":
        print("NASA_API_KEY 未設定のため DEMO_KEY を使います（レート制限が厳しめです）")

    anthropic_client = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        anthropic_client = anthropic.Anthropic()
    else:
        print("ANTHROPIC_API_KEY 未設定のため、英語の原文をそのまま投稿します")

    print("APOD を取得中...")
    try:
        apod = fetch_apod(api_key)
    except requests.HTTPError as e:
        print(f"APOD の取得に失敗しました (HTTP {e.response.status_code})", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as e:
        print(f"APOD の取得に失敗しました ({e})", file=sys.stderr)
        sys.exit(1)

    apod_date = apod.get("date", "")
    if not apod_date or not apod.get("explanation"):
        print(f"APOD のレスポンスが不正です: {str(apod)[:200]}", file=sys.stderr)
        sys.exit(1)

    # 同じ APOD を二重投稿しない（バックアップ起動を安全にするためのガード）
    state = load_state()
    if state.get("last_apod_date") == apod_date:
        print(f"APOD {apod_date}（{apod.get('title')}）は投稿済みのため終了します")
        return

    print(f"  {apod_date}: {apod.get('title')} [{apod.get('media_type')}]")
    print("要約中...")
    digest = summarize(anthropic_client, apod)

    slack = WebClient(token=slack_token)
    slack.chat_postMessage(
        channel=SLACK_CHANNEL,
        blocks=build_blocks(apod, digest),
        text=f"今日の天文学: {digest.get('title_ja') or apod.get('title')}",
        unfurl_links=False,
    )
    print("Slack に投稿しました")

    save_state(apod_date)
    print(f"状態を保存しました（last_apod_date={apod_date}）")


if __name__ == "__main__":
    main()
