## 本家 shoestring からの主な変更点

- プロジェクト名を Sakuya（`konohanasakuya-hime`）に変更し、Python パッケージ名を `symbol-sakuya`、モジュール名を `sakuya` に変更。
- ノードルート直下の設定ファイルを `config.ini`、`overrides.ini`、`rest_overrides.json`、`ca.key.pem` に統一し、生成物を `sakuya/` 配下へ整理。
- `init` で選択したネットワークパッケージを設定ファイルに保存し、`setup` と `upgrade` がその設定を使用するよう変更。両コマンドから `--package` を削除。
- `setup`、`upgrade`、証明書更新の生成・公開を一時領域経由にし、途中で失敗した場合に既存のノード状態を残すよう変更。
- `announce-transaction` に一時的な REST 障害への再試行と、トランザクションの確定・失敗状態の待機を追加。
- 証明書更新時は CA キーとノードキーを既定で再利用し、置き換えを明示的なオプションに変更。CA キーの既定出力権限を `0400` に変更。
- `renew-voting-keys` でオンチェーンのリンクとローカルキーを事前確認し、外部トランザクションの確定前にローカルキーを削除しないよう変更。
- `reset-data` の対象を管理下のディレクトリに限定し、投票状態とハーベスター情報を保持。再構築に失敗した場合はリストアするよう変更。
- 本家の `import-bootstrap`、`import-harvesters` コマンドと、ウィザードの bootstrap インポート画面を削除。
