#!/bin/zsh
cd "${0:A:h}" || exit 1
umask 077
runtime_python="${HOME}/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
if [[ ! -x "$runtime_python" ]]; then runtime_python="$(command -v python3)"; fi
"$runtime_python" scripts/import-wechat-zip.py --choose
import_result=$?
printf '\n按回车关闭此窗口。'
read -r
exit "$import_result"
