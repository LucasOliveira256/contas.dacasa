#!/bin/sh
set -eu
# O volume já existia nas versões anteriores, então corrigimos proprietário e permissões ao iniciar.
mkdir -p /data
chown -R app:app /data
chmod 700 /data
find /data -maxdepth 1 -type f -exec chmod 600 {} \;
umask 077
exec gosu app "$@"
