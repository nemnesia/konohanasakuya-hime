import argparse
import asyncio
import gettext
import importlib
import os
import sys
from pathlib import Path

from sakuya.internal.Directory import resolve_directory


def register_subcommand(subparsers, name, help_text):
	parser = subparsers.add_parser(name, help=help_text)
	parser.set_defaults(command=name)
	module = importlib.import_module(f'sakuya.commands.{name.replace("-", "_")}')
	module.add_arguments(parser)


def parse_args(args):
	parser = argparse.ArgumentParser(description=_('main-title'))
	parser.add_argument('--directory', help=_('argument-help-directory'))
	subparsers = parser.add_subparsers(title='subcommands', help=_('main-subcommands-help'))

	register_subcommand(subparsers, 'announce-transaction', _('main-announce-transaction-help'))
	register_subcommand(subparsers, 'health', _('main-health-help'))
	register_subcommand(subparsers, 'init', _('main-init-help'))
	register_subcommand(subparsers, 'min-cosignatures-count', _('main-min-cosignatures-count-help'))
	register_subcommand(subparsers, 'pemtool', _('main-pemtool-help'))
	register_subcommand(subparsers, 'pemview', _('main-pemview-help'))
	register_subcommand(subparsers, 'renew-certificates', _('main-renew-certificates-help'))
	register_subcommand(subparsers, 'renew-voting-keys', _('main-renew-voting-keys-help'))
	register_subcommand(subparsers, 'reset-data', _('main-reset-data-help'))
	register_subcommand(subparsers, 'setup', _('main-setup-help'))
	register_subcommand(subparsers, 'signer', _('main-signer-help'))
	register_subcommand(subparsers, 'upgrade', _('main-upgrade-help'))

	args = parser.parse_args(args)
	args.directory = resolve_directory(args.directory)
	command = getattr(args, 'command', None)
	default_paths = {
		'config': 'config.ini',
		'overrides': 'overrides.ini',
		'rest_overrides': 'rest_overrides.json',
		'ca_key_path': 'ca.key.pem',
		'input': 'ca.key.pem' if 'pemview' == command else None,
		'output': 'ca.key.pem' if 'pemtool' == command else None
	}
	for name, default_name in default_paths.items():
		if default_name and hasattr(args, name) and getattr(args, name) is None:
			setattr(args, name, str(args.directory / default_name))
	if not hasattr(args, 'func'):
		parser.print_help()
		raise SystemExit()

	return args


async def main(args):
	lang_directory = Path(__file__).resolve().parent / 'lang'
	requested_language = os.environ.get('LC_MESSAGES', 'en').split('.')[0].split('_')[0]
	language = requested_language if requested_language in ('en', 'ja') else 'en'
	lang = gettext.translation('messages', localedir=lang_directory, languages=(language, 'en'))
	lang.install()

	args = parse_args(args)
	possible_task = args.func(args)
	if possible_task:
		await possible_task


if '__main__' == __name__:
	asyncio.run(main(sys.argv[1:]))
