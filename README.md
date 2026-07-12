# claude-routines

Claude Code で動かす自動化ルーティン集。

## Pharmacy News Daily（日刊薬業・PHARMACY NEWSBREAK）

毎朝 6:00 JST に [日刊薬業（nk.jiho.jp）](https://nk.jiho.jp/) と
[PHARMACY NEWSBREAK（pnb.jiho.jp）](https://pnb.jiho.jp/) の新着記事を取得し、
未投稿の記事から 3 件を選んで約 200 字に要約し、Slack の `#薬剤ニュース` チャンネルへ投稿します。
GitHub Actions 上で動くため、**PC やデスクトップアプリが起動していなくても実行されます**。

### 動作概要

1. nk.jiho.jp / pnb.jiho.jp のトップページ・新着一覧から記事リンクを収集
2. `data/pharmacy_seen_articles.json` と照合して未投稿の記事に絞る（重複排除、14 日で失効）
3. 両サイトの記事を交互に並べて先頭 3 件を選び、Claude API（Haiku）で約 200 字に要約
   （`ANTHROPIC_API_KEY` 未設定時は記事リード文の抜粋で代替）
4. Slack `#薬剤ニュース` チャンネルへ投稿
5. 投稿済み URL を `data/pharmacy_seen_articles.json` に保存して main へコミット

### スケジュール

`.github/workflows/pharmacy-news.yml` の `schedule`（cron: `0 21 * * *` UTC = 6:00 JST）で自動実行されます。
GitHub Actions の cron は数分〜十数分遅れることがあります。時刻の正確さが必要な場合は、
DHBR と同様に cron-job.org から `workflow_dispatch` を起動する方式も併用できます。

> **注意**: `schedule` トリガーはデフォルトブランチ（main）のワークフローのみ有効です。
> このワークフローを main にマージすると稼働を開始します。

### セットアップ

GitHub リポジトリの **Settings → Secrets and variables → Actions** に以下を登録してください
（DHBR Daily Digest と共通）。

| Secret 名 | 説明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic コンソールで発行した API キー |
| `SLACK_BOT_TOKEN` | Slack Bot の OAuth トークン（`xoxb-...`） |

Bot を `#薬剤ニュース` チャンネルに招待してください（`/invite @your-bot`）。

### 手動実行

GitHub の **Actions タブ → Pharmacy News Daily → Run workflow** から手動実行できます。

### ローカル実行

```bash
pip install -r scripts/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export SLACK_BOT_TOKEN=xoxb-...
python scripts/pharmacy_news.py
```

## DHBR Daily Digest

毎朝 6:00 JST に [Diamond Harvard Business Review](https://dhbr.diamond.jp/) の新着記事を
取得・要約して Slack の `#hbrまとめ` チャンネルへ投稿します。

### 動作概要

1. dhbr.diamond.jp から最新 10 件の記事を取得
2. `data/seen_articles.json` と照合して未投稿の記事に絞る
3. 上位 3 件を Claude API（Haiku）で 200 字に要約
4. Slack `#hbrまとめ` チャンネルへ投稿
5. 投稿済み URL を `data/seen_articles.json` に保存してコミット

### セットアップ

GitHub リポジトリの **Settings → Secrets and variables → Actions** に以下を登録してください。

| Secret 名 | 説明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic コンソールで発行した API キー |
| `SLACK_BOT_TOKEN` | Slack Bot の OAuth トークン（`xoxb-...`） |

#### Slack Bot に必要なスコープ

- `chat:write` — メッセージ投稿
- `channels:read` / `groups:read` — チャンネル情報読み取り（任意）

Bot を `#hbrまとめ` チャンネルに招待してください（`/invite @your-bot`）。

### 手動実行

GitHub の **Actions タブ → DHBR Daily Digest → Run workflow** から手動実行できます。

### ローカル実行

```bash
pip install -r scripts/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export SLACK_BOT_TOKEN=xoxb-...
python scripts/dhbr_digest.py
```
