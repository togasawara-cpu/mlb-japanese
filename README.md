# MLB日本人選手 前日成績サイト

MLB Stats API から日本人選手の前日試合成績を取得し、毎朝 JST 6:00 に自動更新する静的サイト。

公開先: GitHub Pages (`docs/index.html`)

## 対象選手

大谷翔平、山本由伸、今永昇太、鈴木誠也、吉田正尚、上沢直之、松井裕樹

## ローカル実行

```powershell
pip install requests
python scripts/fetch_stats.py
```

実行後 `docs/index.html` が生成されるので、ブラウザで開いて確認。

## デプロイ手順

1. このリポジトリを GitHub に push
2. リポジトリ Settings → Pages → Source を `Deploy from a branch`、Branch を `main` / `/docs` に設定
3. Settings → Actions → General → Workflow permissions を **Read and write permissions** に変更
4. Actions タブから `MLB Stats Update` を一度手動実行（`Run workflow`）して動作確認

以降は毎朝 JST 6:00 に自動更新される。

## ファイル構成

```
.
├── docs/index.html              # 公開HTML（自動生成）
├── scripts/fetch_stats.py       # 取得・HTML生成スクリプト
└── .github/workflows/update.yml # 毎日6時(JST)実行のActions
```

## データソース

[MLB Stats API](https://statsapi.mlb.com) (公式・無料・APIキー不要)
