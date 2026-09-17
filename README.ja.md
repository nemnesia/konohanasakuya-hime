# Sakuya

[English README](README.md)

Sakuya（`konohanasakuya-hime`）は、Symbol ノードの構築と運用を行うためのツールです。
PyPI パッケージ名は `symbol-sakuya`、Python モジュール名は `sakuya` です。

## セキュリティ

CA 秘密鍵は機密情報です。既定ではノードルートの `ca.key.pem` から読み込み、
Sakuya が作成するファイルには `0400` の権限を設定します。安全にバックアップを保管し、
コンテナから参照できる状態にしないでください。

`pemtool` では暗号化 PEM ファイルを作成できます。ただし、現在のウィザードは暗号化 PEM
ファイルのパスワード入力には対応していません。

## インストール

```sh
python3 -m pip install symbol-sakuya
python3 -m sakuya --help
```

ソースツリーから実行する場合:

```sh
PYTHONPATH=. python3 -m sakuya --help
```

## ディレクトリ構成

ノードルートは、次の優先順で決まります。

1. トップレベルの `--directory`
2. `SAKUYA_HOME`
3. カレントディレクトリ

ユーザーが管理するファイルはノードルート直下に配置します。

```text
config.ini
overrides.ini
rest_overrides.json
ca.key.pem
docker-compose.yaml
docker-compose-recovery.yaml
```

生成されたノードファイルは `sakuya/` 配下に配置されます。主なディレクトリは
`node-config`、`keys`、`data`、`logs`、`seed`、API サポート用ファイルです。
トランザクションファイルはノードルート直下に作成されます。

## 初期セットアップ

ネットワーク設定と既定のオーバーライドファイルを作成します。

```sh
python3 -m sakuya --directory /srv/symbol init
```

ネットワークパッケージは `--package` で選択できます。既定値は `mainnet` です。
`testnet`、`sai`、ローカルの `file://` URI、HTTP(S) URI も指定できます。
プライベートネットワークやカスタムネットワークの場合、パッケージの情報は
`config.ini` の `[package]` セクションに保存されます。

`config.ini` と、必要に応じて `overrides.ini`、`rest_overrides.json` を編集してから、
次のコマンドを実行します。

```sh
python3 -m sakuya --directory /srv/symbol setup
```

`setup` と `upgrade` は `config.ini` からパッケージを解決します。これらのコマンドに
`--package` オプションはありません。セットアップの生成結果は処理が正常に完了した後に
公開されます。生成された linking トランザクションはノードルートに保存され、別途署名・
アナウンスできます。

セットアップトランザクションだけを生成する場合:

```sh
python3 -m sakuya --directory /srv/symbol setup --output-transaction-only
```

## コマンド

利用できるコマンドは次のとおりです。

```text
init
setup
upgrade
signer
announce-transaction
health
min-cosignatures-count
pemtool
pemview
renew-certificates
renew-voting-keys
reset-data
```

ノード設定を使用するコマンドは、既定でノードルートの `config.ini` を使用します。
`setup` は `overrides.ini`、`rest_overrides.json`、`ca.key.pem` も同じノードルートから
読み込みます。

`announce-transaction` はトランザクションファイルを位置引数で受け取ります。

```sh
python3 -m sakuya --directory /srv/symbol announce-transaction transaction.dat
```

このコマンドは、設定されたトランザクションタイムアウトまで、トランザクションが確定
または失敗状態になるのを待機します。

`renew-certificates` は既存の CA キーとノードキーを既定で再利用します。置き換える場合は
`--renew-ca` または `--renew-node-key` を明示的に指定してください。証明書の公開はアトミック
に行われます。

`renew-voting-keys` はトランザクションを作成する前に、アカウントのオンチェーンの投票キー
リンクを確認します。外部トランザクションの状態が確定する前に、ローカルの投票キー
ファイルを削除することはありません。

`reset-data` は `sakuya/` 配下の管理対象ディレクトリだけを操作します。投票状態ファイルと
`harvesters.dat` は保持され、`--purge-harvesters` を指定した場合のみ後者を削除します。
ディレクトリの再構築に失敗した場合は、元の状態に戻します。

## ウィザード

対話型ウィザードは次のコマンドで起動できます。

```sh
python3 -m sakuya.wizard
```

セットアップと運用コマンドに引き続き利用できます。アップグレードでは既存の
`config.ini` を使用し、ネットワークの再設定は行いません。

## ライセンス

MIT License。詳しくは [LICENSE](LICENSE) を参照してください。
