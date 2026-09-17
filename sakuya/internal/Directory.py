import os
from pathlib import Path


def resolve_directory(directory=None):
	"""Resolves the Sakuya node root directory."""

	if directory is not None:
		return Path(directory)

	if os.environ.get('SAKUYA_HOME'):
		return Path(os.environ['SAKUYA_HOME'])

	return Path.cwd()
