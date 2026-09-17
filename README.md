# Sakuya

[日本語版 README](README.ja.md)

Sakuya (`konohanasakuya-hime`) prepares and operates Symbol node deployments.
The PyPI package name is `symbol-sakuya` and the Python module is `sakuya`.

## Security

The CA private key is a sensitive file. By default it is read from
`ca.key.pem` in the node root and is written with mode `0400` when Sakuya
creates it. Keep it backed up securely and do not expose it to containers.

`pemtool` can create an encrypted PEM file. The wizard currently does not
provide a password prompt for encrypted PEM files.

## Installation

```sh
python3 -m pip install symbol-sakuya
python3 -m sakuya --help
```

For a source checkout:

```sh
PYTHONPATH=. python3 -m sakuya --help
```

## Directory layout

The node root is selected in this order: top-level `--directory`,
`SAKUYA_HOME`, then the current directory.

User-managed files are kept in the root:

```text
config.ini
overrides.ini
rest_overrides.json
ca.key.pem
docker-compose.yaml
docker-compose-recovery.yaml
```

Generated node files are kept below `sakuya/`, including `node-config`,
`keys`, `data`, `logs`, `seed`, and API support files. Transaction files are
written in the root.

## Initial setup

Create the network configuration and the default override files:

```sh
python3 -m sakuya --directory /srv/symbol init
```

The package can be selected with `--package`. `mainnet` is the default;
`testnet`, `sai`, a local `file://` URI, or an HTTP(S) URI can be supplied.
For a private or custom network, the source is saved in the `[package]`
section of `config.ini`.

Edit `config.ini` and, if needed, `overrides.ini` and
`rest_overrides.json`, then run:

```sh
python3 -m sakuya --directory /srv/symbol setup
```

`setup` and `upgrade` resolve the package from `config.ini`; they do not take
a package option. Setup generation is staged and published only after it
completes successfully. The generated linking transaction is written to the
root and can be signed and announced separately.

To generate only the setup transaction:

```sh
python3 -m sakuya --directory /srv/symbol setup --output-transaction-only
```

## Commands

The available commands are:

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

All commands that use node configuration default to `config.ini` in the node
root. `setup` also defaults to `overrides.ini`, `rest_overrides.json`, and
`ca.key.pem` in that root.

`announce-transaction` takes the transaction file as a positional argument:

```sh
python3 -m sakuya --directory /srv/symbol announce-transaction transaction.dat
```

The command waits for a confirmed or failed transaction state until the
configured transaction timeout expires.

`renew-certificates` reuses the current CA and node key by default. Use
`--renew-ca` or `--renew-node-key` explicitly to replace them. Certificate
publication is atomic.

`renew-voting-keys` checks the account's on-chain voting-key links before
creating a transaction. Local voting-key files are not removed before the
external transaction state is confirmed.

`reset-data` only operates on managed directories below `sakuya/` and keeps
the voting status file, and `harvesters.dat` unless `--purge-harvesters` is
specified. The reset is rolled back if rebuilding the directories fails.

## Wizard

The interactive wizard is available as:

```sh
python3 -m sakuya.wizard
```

It remains available for setup and operational commands. Upgrade uses the
existing `config.ini`; it does not reconfigure the network.

## License

MIT License. See [LICENSE](LICENSE).
