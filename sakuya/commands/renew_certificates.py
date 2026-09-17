import os
import shutil
import tempfile
from pathlib import Path

from sakuya.internal.AtomicFileSystem import replace_paths
from sakuya.internal.CertificateFactory import CertificateFactory
from sakuya.internal.NodeKeyUtils import write_node_key_file
from sakuya.internal.OpensslExecutor import OpensslExecutor
from sakuya.internal.Preparer import Preparer
from sakuya.internal.SakuyaConfiguration import parse_sakuya_configuration


async def run_main(args):
	config = parse_sakuya_configuration(args.config)
	directories = Preparer.DirectoryLocator(None, Path(args.directory).absolute())

	ca_key_path = Path(args.ca_key_path).absolute()
	if ca_key_path.is_symlink():
		raise RuntimeError(f'CA key path must not be a symbolic link: {ca_key_path}')
	if not ca_key_path.exists():
		raise RuntimeError(f'CA key is required but does not exist at path {ca_key_path}')

	openssl_executor = OpensslExecutor(os.environ.get('OPENSSL_EXECUTABLE', 'openssl'))
	if not directories.certificates.is_dir():
		raise RuntimeError(f'certificate directory does not exist at path {directories.certificates}')

	# commit元と同じファイルシステム上に置き、os.replaceによるatomic更新を保証する。
	staged_directory = Path(tempfile.mkdtemp(dir=directories.certificates.parent, prefix='.sakuya-certificates-'))
	try:
		with CertificateFactory(openssl_executor, ca_key_path, config.node.ca_password) as factory:
			if args.renew_ca:
				factory.generate_ca_certificate(config.node.ca_common_name)
			else:  # 既存のCA証明書を再利用してノード証明書だけを更新する。
				factory.reuse_ca_certificate(config.node.ca_common_name, directories.certificates)

			write_node_key_file(factory, None if args.renew_node_key else directories.certificates / 'node.key.pem')
			factory.generate_node_certificate(config.node.node_common_name)
			factory.create_node_certificate_chain()

			package_filter = '' if args.renew_ca else 'node'
			factory.package(staged_directory, package_filter)

		filenames = CertificateFactory.CERTIFICATE_FILENAMES
		if not args.renew_ca:
			filenames = [filename for filename in filenames if filename.startswith('node')]
		replace_paths(staged_directory, directories.certificates, filenames)
	finally:
		shutil.rmtree(staged_directory, ignore_errors=True)


def add_arguments(parser):
	parser.add_argument('--config', help=_('argument-help-config'))
	parser.add_argument('--ca-key-path', help=_('argument-help-ca-key-path'))
	parser.add_argument('--renew-ca', help=_('argument-help-renew-certificates-renew-ca'), action='store_true')
	parser.add_argument('--renew-node-key', help=_('argument-help-renew-certificates-renew-node-key'), action='store_true')
	parser.set_defaults(func=run_main)
