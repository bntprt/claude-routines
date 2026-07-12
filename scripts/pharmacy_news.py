#!/usr/bin/env python3
"""薬剤ニュースダイジェスト: 日刊薬業（nk.jiho.jp）と PHARMACY NEWSBREAK（pnb.jiho.jp）の
新着記事を取得し、未投稿3件を200字要約してSlackへ投稿する。"""

import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from slack_sdk import WebClient

JST = timezone(timedelta(hours=9))

DATA_FILE = Path(__file__).parent.parent / "data" / "pharmacy_seen_articles.json"
SLACK_CHANNEL = "C0BFUN7AJHJ"  # #薬剤ニュース
SELECT_COUNT = 3
EXPIRE_DAYS = 14  # この日数を過ぎたら既読リストから自動削除
SUMMARY_LENGTH = 200

SOURCES = [
    {"name": "日刊薬業", "base": "https://nk.jiho.jp"},
    {"name": "PHARMACY NEWSBREAK", "base": "https://pnb.jiho.jp"},
]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

# 記事ページとして扱わないパス（一覧・案内ページなど）
EXCLUDE_PATH_PATTERNS = re.compile(
    r"/(login|logout|entry|register|mypage|guide|company|policy|privacy|terms|"
    r"contact|search|tag|category|list|ranking|about|help|sitemap|rss)",
    re.IGNORECASE,
)


def load_seen_data() -> dict[str, str]:
    """既読データを読み込み、有効期限切れエントリを除外して返す。{url: "YYYY-MM-DD"}"""
    if not DATA_FILE.exists():
        return {}
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw.get("articles"), dict):
        return {}
    cutoff = date.today() - timedelta(days=EXPIRE_DAYS)
    return {
        url: seen_on
        for url, seen_on in raw["articles"].items()
        if date.fromisoformat(seen_on) >= cutoff
    }


def save_seen_data(data: dict[str, str]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps({"articles": data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _get_soup(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, timeout=20, headers=REQUEST_HEADERS)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except Exception as e:
        print(f"  取得失敗: {url} ({e})", file=sys.stderr)
        return None


def _normalize_url(href: str, base: str) -> str | None:
    if href.startswith("/"):
        href = base + href
    if not href.startswith(base):
        return None
    return href.split("#")[0].split("?")[0]


def _extract_articles(soup: BeautifulSoup, base: str, seen_in_fetch: set) -> list[dict]:
    """ページ内のリンクから記事候補を抽出する。/article/ 形式のURLを優先する。"""
    primary: list[dict] = []   # 記事URLパターンに一致
    secondary: list[dict] = []  # その他の内部リンク（タイトルが記事らしいもの）

    for tag in soup.find_all("a", href=True):
        url = _normalize_url(tag["href"], base)
        if url is None or url in seen_in_fetch or url.rstrip("/") == base:
            continue
        title = tag.get_text(" ", strip=True)
        if len(title) < 12:
            continue
        if EXCLUDE_PATH_PATTERNS.search(url):
            continue
        seen_in_fetch.add(url)
        entry = {"title": title, "url": url}
        if re.search(r"/article[s]?/\d+", url) or re.search(r"/\d{5,}", url):
            primary.append(entry)
        else:
            secondary.append(entry)

    return primary + secondary


def fetch_new_articles(source: dict) -> list[dict]:
    """指定サイトのトップページと新着系ページから記事候補を収集する。"""
    base = source["base"]
    seen_in_fetch: set[str] = set()
    results: list[dict] = []

    soup = _get_soup(base + "/")
    if soup is not None:
        found = _extract_articles(soup, base, seen_in_fetch)
        print(f"  [{source['name']}] トップページから {len(found)} 件取得")
        results.extend(found)
    else:
        print(f"[{source['name']}] トップページの取得に失敗しました", file=sys.stderr)

    # 新着一覧らしきページを補完として試す
    for path in ["/list/latest", "/latest", "/new", "/news", "/article"]:
        if len(results) >= 30:
            break
        soup = _get_soup(base + path)
        if soup is None:
            continue
        found = _extract_articles(soup, base, seen_in_fetch)
        if found:
            print(f"  [{source['name']}] {path} から追加 {len(found)} 件取得")
            results.extend(found)

    print(f"  [{source['name']}] 合計取得: {len(results)} 件")
    return [{**a, "source": source["name"]} for a in results[:30]]


def interleave_sources(per_source: list[list[dict]]) -> list[dict]:
    """各サイトの記事を交互に並べ、投稿がどちらかのサイトに偏らないようにする。"""
    merged: list[dict] = []
    max_len = max((len(lst) for lst in per_source), default=0)
    for i in range(max_len):
        for lst in per_source:
            if i < len(lst):
                merged.append(lst[i])
    return merged


def fetch_article_text(url: str) -> str:
    """記事ページから要約用の本文テキスト（リード文）を取得する。有料記事は冒頭のみ。"""
    soup = _get_soup(url)
    if soup is None:
        return ""

    parts: list[str] = []
    for attr in [
        {"property": "og:description"},
        {"name": "description"},
        {"name": "twitter:description"},
    ]:
        tag = soup.find("meta", attrs=attr)
        if tag and tag.get("content", "").strip():
            parts.append(tag["content"].strip())
            break

    for sel in ["article", ".article-body", ".articleBody", ".entry-content", "main"]:
        el = soup.select_one(sel)
        if el:
            for p in el.find_all("p"):
                text = p.get_text(strip=True)
                if len(text) >= 20:
                    parts.append(text)
                if sum(len(t) for t in parts) > 1500:
                    break
            break

    return "\n".join(dict.fromkeys(parts))[:1500]


def summarize(client, title: str, body: str) -> str:
    """Claude（Haiku）で約200字の日本語要約を生成する。失敗時は本文冒頭で代替。"""
    fallback = (body.replace("\n", " ")[:SUMMARY_LENGTH]) if body else ""
    if client is None or not (title or body):
        return fallback

    import anthropic

    prompt = (
        "以下は医薬品業界ニュース記事のタイトルと本文（冒頭部分のみの場合があります）です。"
        f"薬剤師・製薬業界関係者向けに、日本語約{SUMMARY_LENGTH}字（±20字）で要約してください。"
        "前置きや見出しは不要で、要約本文のみを出力してください。\n\n"
        f"タイトル: {title}\n\n本文:\n{body if body else '（本文取得不可。タイトルから内容を簡潔に説明）'}"
    )
    try:
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        return text.strip() or fallback
    except anthropic.APIStatusError as e:
        print(f"  要約APIエラー ({e.status_code}): 本文冒頭で代替します", file=sys.stderr)
    except anthropic.APIConnectionError:
        print("  要約API接続エラー: 本文冒頭で代替します", file=sys.stderr)
    except Exception as e:
        print(f"  要約失敗 ({e}): 本文冒頭で代替します", file=sys.stderr)
    return fallback


def post_to_slack(slack: WebClient, items: list[dict]) -> None:
    today = datetime.now(JST).strftime("%Y年%m月%d日")
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"💊 薬剤ニュースまとめ（{today}）",
                "emoji": True,
            },
        }
    ]
    for i, art in enumerate(items, 1):
        blocks.append({"type": "divider"})
        body_text = f"*{i}. <{art['url']}|{art['title']}>*"
        if art.get("source"):
            body_text += f"　`{art['source']}`"
        if art.get("summary"):
            body_text += f"\n{art['summary']}"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body_text}})

    slack.chat_postMessage(
        channel=SLACK_CHANNEL,
        blocks=blocks,
        text=f"薬剤ニュースまとめ（{today}）",
        unfurl_links=False,
    )


def main() -> None:
    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not slack_token:
        print("SLACK_BOT_TOKEN が設定されていません", file=sys.stderr)
        sys.exit(1)

    anthropic_client = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic

        anthropic_client = anthropic.Anthropic()
    else:
        print("ANTHROPIC_API_KEY 未設定のため、要約は本文冒頭の抜粋で代替します")

    seen_data = load_seen_data()
    seen_urls = set(seen_data.keys())
    print(f"既読: {len(seen_urls)} 件（{EXPIRE_DAYS}日以内）")

    print("新着記事を取得中...")
    per_source_unseen: list[list[dict]] = []
    total_fetched = 0
    for source in SOURCES:
        articles = fetch_new_articles(source)
        total_fetched += len(articles)
        per_source_unseen.append([a for a in articles if a["url"] not in seen_urls])

    if total_fetched == 0:
        print("記事の取得に失敗しました", file=sys.stderr)
        sys.exit(1)

    unseen = interleave_sources(per_source_unseen)
    print(f"未投稿: {len(unseen)} 件（既読除外後）")

    if not unseen:
        print("新着の未投稿記事がないためスキップします")
        return

    selected = unseen[:SELECT_COUNT]

    results = []
    for art in selected:
        print(f"  要約中: [{art['source']}] {art['title'][:40]}...")
        body = fetch_article_text(art["url"])
        summary = summarize(anthropic_client, art["title"], body)
        results.append({**art, "summary": summary})

    post_to_slack(WebClient(token=slack_token), results)
    print(f"Slack に投稿しました（{len(results)} 件）")

    today_str = datetime.now(JST).date().isoformat()
    for art in selected:
        seen_data[art["url"]] = today_str
    save_seen_data(seen_data)
    print(f"既読リストを更新しました（計 {len(seen_data)} 件）")


if __name__ == "__main__":
    main()
