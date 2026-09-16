import os
from pathlib import Path


def resolve_directory(directory=None):
	"""Resolves the common Shoestring output directory."""

	if directory is not None:
		return Path(directory)

	if os.environ.get('SHOESTRING_HOME'):
		return Path(os.environ['SHOESTRING_HOME'])

	return Path.cwd()
