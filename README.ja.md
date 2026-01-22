<p align="center">
  <img width="100%" alt="Hive Banner" src="https://storage.googleapis.com/aden-prod-assets/website/aden-title-card.png" />
</p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="README.zh-CN.md">简体中文</a> |
  <a href="README.es.md">Español</a> |
  <a href="README.pt.md">Português</a> |
  <a href="README.ja.md">日本語</a> |
  <a href="README.ru.md">Русский</a>
</p>

[![Apache 2.0 License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/adenhq/hive/blob/main/LICENSE)
[![Y Combinator](https://img.shields.io/badge/Y%20Combinator-Aden-orange)](https://www.ycombinator.com/companies/aden)
[![Docker Pulls](https://img.shields.io/docker/pulls/adenhq/hive?logo=Docker&labelColor=%23528bff)](https://hub.docker.com/u/adenhq)
[![Discord](https://img.shields.io/discord/1172610340073242735?logo=discord&labelColor=%235462eb&logoColor=%23f5f5f5&color=%235462eb)](https://discord.com/invite/MXE49hrKDk)
[![Twitter Follow](https://img.shields.io/twitter/follow/teamaden?logo=X&color=%23f5f5f5)](https://x.com/aden_hq)
[![LinkedIn](https://custom-icon-badges.demolab.com/badge/LinkedIn-0A66C2?logo=linkedin-white&logoColor=fff)](https://www.linkedin.com/company/teamaden/)

<p align="center">
  <img src="https://img.shields.io/badge/AI_Agents-Self--Improving-brightgreen?style=flat-square" alt="AI Agents" />
  <img src="https://img.shields.io/badge/Multi--Agent-Systems-blue?style=flat-square" alt="Multi-Agent" />
  <img src="https://img.shields.io/badge/Goal--Driven-Development-purple?style=flat-square" alt="Goal-Driven" />
  <img src="https://img.shields.io/badge/Human--in--the--Loop-orange?style=flat-square" alt="HITL" />
  <img src="https://img.shields.io/badge/Production--Ready-red?style=flat-square" alt="Production" />
</p>
<p align="center">
  <img src="https://img.shields.io/badge/OpenAI-supported-412991?style=flat-square&logo=openai" alt="OpenAI" />
  <img src="https://img.shields.io/badge/Anthropic-supported-d4a574?style=flat-square" alt="Anthropic" />
  <img src="https://img.shields.io/badge/Google_Gemini-supported-4285F4?style=flat-square&logo=google" alt="Gemini" />
  <img src="https://img.shields.io/badge/MCP-19_Tools-00ADD8?style=flat-square" alt="MCP" />
</p>

## 概要

ワークフローをハードコーディングせずに、信頼性の高い自己改善型AIエージェントを構築できます。コーディングエージェントとの会話を通じて目標を定義すると、フレームワークが動的に作成された接続コードを持つノードグラフを生成します。問題が発生すると、フレームワークは障害データをキャプチャし、コーディングエージェントを通じてエージェントを進化させ、再デプロイします。組み込みのヒューマンインザループノード、認証情報管理、リアルタイムモニタリングにより、適応性を損なうことなく制御を維持できます。

完全なドキュメント、例、ガイドについては [adenhq.com](https://adenhq.com) をご覧ください。

## Adenとは

<p align="center">
  <img width="100%" alt="Aden Architecture" src="docs/assets/aden-architecture-diagram.jpg" />
</p>

Adenは、AIエージェントの構築、デプロイ、運用、適応のためのプラットフォームです：

- **構築** - コーディングエージェントが自然言語の目標から専門的なワーカーエージェント（セールス、マーケティング、オペレーション）を生成
- **デプロイ** - CI/CD統合と完全なAPIライフサイクル管理を備えたヘッドレスデプロイメント
- **運用** - リアルタイムモニタリング、可観測性、ランタイムガードレールがエージェントの信頼性を維持
- **適応** - 継続的な評価、監督、適応により、エージェントは時間とともに改善
- **インフラ** - 共有メモリ、LLM統合、ツール、スキルがすべてのエージェントを支援

## クイックリンク

- **[ドキュメント](https://docs.adenhq.com/)** - 完全なガイドとAPIリファレンス
- **[セルフホスティングガイド](https://docs.adenhq.com/getting-started/quickstart)** - インフラストラクチャへのHiveデプロイ
- **[変更履歴](https://github.com/adenhq/hive/releases)** - 最新の更新とリリース
- **[問題を報告](https://github.com/adenhq/hive/issues)** - バグレポートと機能リクエスト

## クイックスタート

### 前提条件

- [Docker](https://docs.docker.com/get-docker/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2.0+)

### インストール

```bash
# リポジトリをクローン
git clone https://github.com/adenhq/hive.git
cd hive

# コピーして設定
cp config.yaml.example config.yaml

# セットアップを実行してサービスを開始
npm run setup
docker compose up
```

**アプリケーションにアクセス：**

- ダッシュボード：http://localhost:3000
- API：http://localhost:4000
- ヘルスチェック：http://localhost:4000/health

## 機能

- **目標駆動開発** - 自然言語で目標を定義；コーディングエージェントがそれを達成するためのエージェントグラフと接続コードを生成
- **自己適応エージェント** - フレームワークが障害をキャプチャし、目標を更新し、エージェントグラフを更新
- **動的ノード接続** - 事前定義されたエッジなし；接続コードは目標に基づいて任意の対応LLMによって生成
- **SDKラップノード** - すべてのノードが共有メモリ、ローカルRLMメモリ、モニタリング、ツール、LLMアクセスを標準装備
- **ヒューマンインザループ** - 設定可能なタイムアウトとエスカレーションを備えた、人間の入力のために実行を一時停止する介入ノード
- **リアルタイム可観測性** - エージェント実行、決定、ノード間通信のライブモニタリングのためのWebSocketストリーミング
- **コストと予算管理** - 支出制限、スロットル、自動モデル劣化ポリシーを設定
- **本番環境対応** - セルフホスト可能、スケールと信頼性のために構築

## なぜAdenか

従来のエージェントフレームワークでは、ワークフローを手動で設計し、エージェントの相互作用を定義し、障害を事後的に処理する必要があります。Adenはこのパラダイムを逆転させます—**結果を記述すれば、システムが自ら構築します**。

### Adenの優位性

| 従来のフレームワーク | Aden |
|----------------------|------|
| エージェントワークフローをハードコード | 自然言語で目標を記述 |
| 手動でグラフを定義 | 自動生成されるエージェントグラフ |
| 事後的なエラー処理 | プロアクティブな自己進化 |
| 静的なツール設定 | 動的なSDKラップノード |
| 別途モニタリング設定 | 組み込みのリアルタイム可観測性 |
| DIY予算管理 | 統合されたコスト制御と劣化 |

### 仕組み

1. **目標を定義** → 達成したいことを平易な言葉で記述
2. **コーディングエージェントが生成** → エージェントグラフ、接続コード、テストケースを作成
3. **ワーカーが実行** → SDKラップノードが完全な可観測性とツールアクセスで実行
4. **コントロールプレーンが監視** → リアルタイムメトリクス、予算執行、ポリシー管理
5. **自己改善** → 障害時、システムがグラフを進化させ自動的に再デプロイ

## プロジェクト構造

```
hive/
├── honeycomb/          # フロントエンド (React + TypeScript + Vite)
├── hive/               # バックエンド (Node.js + TypeScript + Express)
├── docs/               # ドキュメント
├── scripts/            # ビルドとユーティリティスクリプト
├── config.yaml.example # 設定テンプレート
└── docker-compose.yml  # コンテナオーケストレーション
```

## 開発

### ホットリロードでのローカル開発

```bash
# 開発用オーバーライドをコピー
cp docker-compose.override.yml.example docker-compose.override.yml

# ホットリロードを有効にして開始
docker compose up
```

### Dockerなしで実行

```bash
# 依存関係をインストール
npm install

# 環境ファイルを生成
npm run generate:env

# フロントエンドを開始（honeycomb/内）
cd honeycomb && npm run dev

# バックエンドを開始（hive/内）
cd hive && npm run dev
```

## ドキュメント

- **[開発者ガイド](DEVELOPER.md)** - 開発者向け総合ガイド
- [はじめに](docs/getting-started.md) - クイックセットアップ手順
- [設定ガイド](docs/configuration.md) - すべての設定オプション
- [アーキテクチャ概要](docs/architecture.md) - システム設計と構造

## ロードマップ

Adenエージェントフレームワークは、開発者が結果志向で自己適応するエージェントを構築できるよう支援することを目指しています。ロードマップはこちらをご覧ください：

[ROADMAP.md](ROADMAP.md)

## コミュニティとサポート

サポート、機能リクエスト、コミュニティディスカッションには[Discord](https://discord.com/invite/MXE49hrKDk)を使用しています。

- Discord - [コミュニティに参加](https://discord.com/invite/MXE49hrKDk)
- Twitter/X - [@adenhq](https://x.com/aden_hq)
- LinkedIn - [会社ページ](https://www.linkedin.com/company/teamaden/)

## 貢献

貢献を歓迎します！ガイドラインについては[CONTRIBUTING.md](CONTRIBUTING.md)をご覧ください。

1. リポジトリをフォーク
2. 機能ブランチを作成 (`git checkout -b feature/amazing-feature`)
3. 変更をコミット (`git commit -m 'Add amazing feature'`)
4. ブランチにプッシュ (`git push origin feature/amazing-feature`)
5. プルリクエストを開く

## チームに参加

**採用中です！** エンジニアリング、リサーチ、マーケティングの役職で私たちに参加してください。

[オープンポジションを見る](https://jobs.adenhq.com/a8cec478-cdbc-473c-bbd4-f4b7027ec193/applicant)

## セキュリティ

セキュリティに関する懸念については、[SECURITY.md](SECURITY.md)をご覧ください。

## ライセンス

このプロジェクトはApache License 2.0の下でライセンスされています - 詳細は[LICENSE](LICENSE)ファイルをご覧ください。

## よくある質問 (FAQ)

**Q: AdenはLangChainや他のエージェントフレームワークに依存していますか？**

いいえ。AdenはLangChain、CrewAI、その他のエージェントフレームワークに依存せずにゼロから構築されています。フレームワークは軽量で柔軟に設計されており、事前定義されたコンポーネントに依存するのではなく、エージェントグラフを動的に生成します。

**Q: AdenはどのLLMプロバイダーをサポートしていますか？**

AdenはOpenAI（GPT-4、GPT-4o）、Anthropic（Claudeモデル）、Google Geminiを標準でサポートしています。アーキテクチャはSDK抽象化によりプロバイダー非依存であり、拡張モデルサポートのためのLiteLLM統合がロードマップにあります。

**Q: Adenはオープンソースですか？**

はい、AdenはApache License 2.0の下で完全にオープンソースです。コミュニティの貢献とコラボレーションを積極的に奨励しています。

**Q: Adenはどのデプロイオプションをサポートしていますか？**

Adenは本番環境と開発環境の両方の設定でDocker Composeデプロイを標準でサポートしています。セルフホストデプロイはDockerをサポートする任意のインフラストラクチャで動作します。クラウドデプロイオプションとKubernetes対応設定はロードマップにあります。

**Q: Adenは複雑な本番規模のユースケースを処理できますか？**

はい。Adenは自動障害回復、リアルタイム可観測性、コスト制御、水平スケーリングサポートなどの機能を備え、本番環境向けに明示的に設計されています。フレームワークは単純な自動化から複雑なマルチエージェントワークフローまで処理できます。

**Q: Adenはヒューマンインザループワークフローをサポートしていますか？**

はい、Adenは人間の入力のために実行を一時停止する介入ノードを通じて、ヒューマンインザループワークフローを完全にサポートしています。設定可能なタイムアウトとエスカレーションポリシーが含まれており、人間の専門家とAIエージェントのシームレスなコラボレーションを可能にします。

**Q: Adenに貢献するにはどうすればよいですか？**

貢献を歓迎します！リポジトリをフォークし、機能ブランチを作成し、変更を実装して、プルリクエストを送信してください。詳細なガイドラインについては[CONTRIBUTING.md](CONTRIBUTING.md)をご覧ください。

---

<p align="center">
  サンフランシスコで 🔥 情熱を込めて作成
</p>
