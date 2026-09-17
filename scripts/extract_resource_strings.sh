#!/bin/bash

set -ex

pybabel extract --omit-header --sort-output -o sakuya/lang/messages.pot sakuya/*.py sakuya/**/*.py sakuya/**/**/*.py

for lang in "en" "ja";
do
	# note: to add a new language, use `init` instead of `update`
	pybabel update  --omit-header -l "${lang}" -i sakuya/lang/messages.pot -d sakuya/lang

	mv "sakuya/lang/${lang}/LC_MESSAGES/messages.po" "sakuya/lang/${lang}/LC_MESSAGES/messages.po.tmp"
	cat "sakuya/lang/po.header.txt" "sakuya/lang/${lang}/LC_MESSAGES/messages.po.tmp" > "sakuya/lang/${lang}/LC_MESSAGES/messages.po"
	rm "sakuya/lang/${lang}/LC_MESSAGES/messages.po.tmp"
done
