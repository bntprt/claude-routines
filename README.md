# claude-routines

Claude Code で動かす自動化ルーティン集。

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
