import gettext

lang = gettext.translation('messages', localedir='sakuya/lang', languages=('en',))
lang.install()
