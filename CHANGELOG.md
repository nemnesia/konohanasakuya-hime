## メモ（正式な changelog ではない）

- `sakuya` CLI（正式名称: `konohanasakuya-hime`）の `--directory` を、各サブコマンド固有の引数からトップレベルの共通オプションへ変更。
- ディレクトリの解決順は `--directory` → `SHOESTRING_HOME` → カレントディレクトリ。
- `--directory` 省略時の暗黙の `$HOME` 使用を廃止。
- 旧形式の `sakuya health --directory ...` ではなく、`sakuya --directory ... health` を使用する。
