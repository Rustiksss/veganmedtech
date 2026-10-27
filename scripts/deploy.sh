#!/usr/bin/env bash
# Закрытое синтетическое демо. SSH настраивается отдельно; паролей в скрипте нет.
set -Eeuo pipefail
INTERNET=0
RAM_STAGE=0

die() { printf 'Ошибка: %s\n' "$*" >&2; exit 1; }
require_root() { [[ $(id -u) == 0 ]] || die 'На сервере требуется root.'; }

require_space() {
    local available required=$2
    [[ $required =~ ^[0-9]+$ ]] || die 'Некорректная оценка места.'
    available=$(df -Pk "$1" | awk 'NR == 2 {print $4}')
    [[ $available =~ ^[0-9]+$ ]] || die 'Не удалось проверить свободное место.'
    (( available * 1024 >= required )) || die "Недостаточно места: свободно $((available / 1024)) MiB, требуется $((required / 1048576)) MiB. Автоматической очистки данных нет."
}

package_source() {
    python3 - "$1" "$2" <<'PY'
import fnmatch
import os
from pathlib import Path
import stat
import sys
import tarfile

root, destination = Path(sys.argv[1]), sys.argv[2]
entries = ('backend', 'frontend/templates', 'frontend/static', 'compose.yaml',
           'compose.deploy.yaml', '.dockerignore', 'scripts/deploy.sh',
           'deploy/Caddyfile', 'deploy/veganmedtech-proxy.service')
excluded = {'.git', '.aws', '.codex', '.agents', '.ssh', '.venv', '__pycache__',
            'node_modules', 'staticfiles'}
patterns = ('.env*', '*.pem', '*.key', '*.pub', '*.pyc', '*.pyo', '*.log',
            '*.sqlite*', '*.db', 'id_rsa*', 'id_ed25519*')
files = []

def collect(path):
    if path.name in excluded or any(fnmatch.fnmatch(path.name, p) for p in patterns):
        return
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        raise ValueError('Символические ссылки в поставке запрещены')
    if stat.S_ISDIR(mode):
        for child in sorted(path.iterdir()):
            collect(child)
    elif stat.S_ISREG(mode):
        files.append(path)
    else:
        raise ValueError('В поставке допустимы только обычные файлы и каталоги')

try:
    for entry in entries:
        path = root / entry
        # Проверяются и промежуточные каталоги (например, frontend).
        if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
            raise ValueError('Символические ссылки в поставке запрещены')
        collect(path)
    if destination == '-':
        for path in files:
            print(path.relative_to(root).as_posix())
    else:
        with tarfile.open(destination, 'w:gz', dereference=False) as archive:
            for path in files:
                # O_NOFOLLOW исключает чтение подменённой ссылки между обходом и упаковкой.
                with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source:
                    info = archive.gettarinfo(str(path), str(path.relative_to(root)))
                    if not info.isfile():
                        raise ValueError('Файл изменился во время упаковки')
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    info.mode = 0o644
                    archive.addfile(info, source)
except (OSError, ValueError, tarfile.TarError):
    sys.exit('Ошибка: не удалось подготовить разрешённый набор файлов; проверьте структуру и ссылки.')
PY
}

# Единственная операция, принимающая поток архива. Блокировка остаётся у процесса
# до завершения дочернего деплоя, в том числе при разрыве локального соединения.
receive_release() {
    local base=$1 release_id=$2 required=$3 directory internet=${4:-0} ram_proof=${5:-}
    require_root
    [[ $release_id =~ ^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$ ]] || die 'Некорректный ID версии.'
    umask 077
    [[ ! -L $base ]] || die 'Каталог поставки не может быть ссылкой.'
    if [[ -e $base && ! -f $base/.owner ]]; then
        [[ -d $base && -z $(find "$base" -mindepth 1 -maxdepth 1 -print -quit) ]] \
            || die 'Целевой каталог занят неизвестной установкой.'
    fi
    # Полный размер готового образа + транспорт + резерв, до приёма архива.
    require_space "$(dirname "$base")" "$required"
    mkdir -p -- "$base"
    [[ ! -L $base/.deploy.lock && ! -L $base/.owner ]] || die 'Некорректные служебные файлы.'
    exec 9>"$base/.deploy.lock"
    flock -n 9 || die 'Другой деплой уже выполняется.'
    if [[ -e $base/.owner ]]; then
        [[ $(cat "$base/.owner") == veganmedtech-work0012-v1 ]] || die 'Неизвестная установка.'
    else
        printf '%s\n' veganmedtech-work0012-v1 > "$base/.owner"
    fi
    chmod 700 "$base"
    for directory in releases config backups; do
        [[ ! -L $base/$directory ]] || die 'Служебный каталог не может быть ссылкой.'
        mkdir -p -- "$base/$directory"
        chmod 700 "$base/$directory"
    done
    if [[ -n $ram_proof ]]; then
        [[ $internet == 1 && $(can_stage_image_in_ram "$ram_proof") == 1 ]] \
            || die 'Изменились предпосылки RAM-поставки; передача остановлена.'
    fi
    local release="$base/releases/$release_id"
    mkdir -- "$release"
    tar --no-same-owner --no-same-permissions -xf - -C "$release" \
        || die 'Передача не завершена; версия не запускается.'
    if [[ -n $ram_proof ]]; then
        bash "$release/scripts/deploy.sh" --remote-internet-ram
    elif [[ $internet == 1 ]]; then
        bash "$release/scripts/deploy.sh" --remote-internet
    else
        bash "$release/scripts/deploy.sh" --remote
    fi
}

ensure_engine() {
    local package version distro codename architecture temporary
    if ! command -v docker >/dev/null; then
        [[ -f /etc/os-release ]] || die 'Не удалось определить ОС.'
        # Файл операционной системы, не пользовательская конфигурация.
        . /etc/os-release
        distro=${ID:-}; codename=${VERSION_CODENAME:-}
        case "$distro:${VERSION_ID:-}" in
            ubuntu:22.04|ubuntu:24.04|ubuntu:26.04|ubuntu:26.10|debian:12|debian:13) ;;
            *) die 'Автоустановка Docker доступна только на поддерживаемой Debian/Ubuntu.' ;;
        esac
        for package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx \
                       podman-docker containerd runc; do
            version=$(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true)
            [[ $version != installed ]] || die 'Найдены конфликтующие пакеты; установка остановлена.'
        done
        architecture=$(dpkg --print-architecture)
        [[ $architecture == amd64 || $architecture == arm64 ]] || die 'Архитектура не проверена.'
        printf 'Установка Docker из официального репозитория для %s %s (%s).\n' "$distro" "$codename" "$architecture"
        DEBIAN_FRONTEND=noninteractive apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl python3
        temporary=$(mktemp -d)
        curl --fail --silent --show-error --proto '=https' \
            "https://download.docker.com/linux/$distro/gpg" -o "$temporary/docker.asc"
        printf 'Types: deb\nURIs: https://download.docker.com/linux/%s\nSuites: %s\nComponents: stable\nArchitectures: %s\nSigned-By: /etc/apt/keyrings/docker.asc\n' \
            "$distro" "$codename" "$architecture" > "$temporary/docker.sources"
        for package in /etc/apt/keyrings/docker.asc /etc/apt/sources.list.d/docker.sources; do
            [[ ! -L $package ]] || die 'Настройка Docker не может быть ссылкой.'
            [[ ! -e $package ]] || cmp -s "$package" "$temporary/${package##*/}" \
                || die 'Существующая настройка репозитория отличается; перезапись запрещена.'
        done
        install -d -m 0755 /etc/apt/keyrings
        install -m 0644 "$temporary/docker.asc" /etc/apt/keyrings/docker.asc
        install -m 0644 "$temporary/docker.sources" /etc/apt/sources.list.d/docker.sources
        rm -r -- "$temporary"
        DEBIAN_FRONTEND=noninteractive apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi
    docker info >/dev/null 2>&1 || die 'Docker недоступен; существующий сервис автоматически не меняется.'
    docker compose version >/dev/null 2>&1 || die 'Нужен рабочий Docker Compose plugin.'
    docker compose up --help | grep -F -- --wait-timeout > /dev/null || die 'Compose должен поддерживать up --wait-timeout.'
    for package in python3 curl; do
        command -v "$package" >/dev/null || die "На сервере нужна команда $package."
    done
    docker --version
    docker compose version
}

check_server_state() {
    local id marker running bindings existing=0
    local owned_ports=''
    for id in $(docker ps -aq --filter label=com.docker.compose.project=veganmedtech); do
        marker=$(docker inspect -f '{{index .Config.Labels "io.veganmedtech.deployment"}}' "$id")
        [[ $marker == work0012 ]] || die 'Имя Compose-проекта занято неизвестными контейнерами.'
        existing=1
        running=$(docker inspect -f '{{.State.Running}}' "$id")
        if [[ $running == true ]]; then
            bindings=$(docker inspect -f '{{json .HostConfig.PortBindings}}' "$id")
            owned_ports+="$(python3 -c '
import json, sys
for bindings in (json.load(sys.stdin) or {}).values():
    for entry in bindings or []:
        if entry["HostIp"] != "127.0.0.1":
            sys.exit("Ошибка: существующий контейнер имеет публичную привязку порта.")
        print(entry["HostPort"])
' <<< "$bindings")"$'\n'
        fi
    done
    if docker volume inspect veganmedtech_postgres_data >/dev/null 2>&1; then
        marker=$(docker volume inspect -f '{{index .Labels "io.veganmedtech.deployment"}}' veganmedtech_postgres_data)
        [[ $marker == work0012 ]] || die 'Том БД принадлежит неизвестной установке.'
        existing=1
    fi
    if docker network inspect veganmedtech_default >/dev/null 2>&1; then
        marker=$(docker network inspect -f '{{index .Labels "io.veganmedtech.deployment"}}' veganmedtech_default)
        [[ $marker == work0012 ]] || die 'Сеть принадлежит неизвестной установке.'
    fi
    if [[ ! -f $1/config/server.env ]]; then
        [[ $existing == 0 ]] || die 'Для существующего проекта отсутствует конфигурация; новые секреты не создаются.'
        ! docker network inspect veganmedtech_default >/dev/null 2>&1 \
            || die 'Сеть проекта уже существует без конфигурации.'
    fi
    python3 - "$owned_ports" <<'PY'
import socket
import sys
owned = sys.argv[1].split()
for port in (18008, 18025):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            if str(port) not in owned:
                sys.exit('Ошибка: порт поставки уже занят посторонним процессом.')
PY
}

ensure_environment() {
    python3 - "$1" "${2:-closed}" <<'PY'
import os
from pathlib import Path
import re
import secrets
import stat
import sys

path = Path(sys.argv[1])
fixed = dict(POSTGRES_DB='compass', POSTGRES_USER='compass', APP_DEV_MODE='1',
    APP_BASE_URL='http://localhost:18008', DJANGO_ALLOWED_HOSTS='localhost,127.0.0.1',
    APP_PORT='18008', MAIL_PORT='18025', SMTP_HOST='mailpit', SMTP_PORT='1025',
    SMTP_TLS='0', MAIL_FROM='no-reply@example.test')
try:
    if not path.exists() and not path.is_symlink():
        values = dict(fixed, DJANGO_SECRET_KEY=secrets.token_urlsafe(64),
                      POSTGRES_PASSWORD=secrets.token_urlsafe(32))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(''.join(f'{k}={v}\n' for k, v in values.items()))
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_uid != os.getuid() or info.st_size > 16384):
        raise ValueError()
    values = {}
    for line in path.read_text().splitlines():
        key, value = line.split('=', 1)
        if key in values:
            raise ValueError()
        values[key] = value
    mode = sys.argv[2]
    if mode == 'either':
        mode = 'internet' if values.get('APP_DEV_MODE') == '0' else 'closed'
    if mode == 'internet':
        fixed.update(APP_DEV_MODE='0', APP_BASE_URL='https://94.103.3.149',
            DJANGO_ALLOWED_HOSTS='94.103.3.149,localhost,127.0.0.1', APP_TRUST_PROXY='1')
    elif mode != 'closed':
        raise ValueError()
    required = set(fixed) | {'DJANGO_SECRET_KEY', 'POSTGRES_PASSWORD'}
    polza = {'POLZA_API_KEY', 'POLZA_MODEL'}
    optional = {'ASSISTANT_ALERTING_MODE'}
    if set(values) - optional not in (required, required | polza):
        raise ValueError()
    if 'ASSISTANT_ALERTING_MODE' in values and values['ASSISTANT_ALERTING_MODE'] not in {'off', 'demo'}:
        raise ValueError()
    if 'POLZA_API_KEY' in values:
        if (not re.fullmatch(r'pza_[A-Za-z0-9_-]{20,200}', values['POLZA_API_KEY'])
                or values['POLZA_MODEL'] not in {'deepseek/deepseek-v4-flash', 'cohere/command-r7b-12-2024'}):
            raise ValueError()
    if any(values[k] != v for k, v in fixed.items()):
        raise ValueError()
    for key, minimum in (('DJANGO_SECRET_KEY', 50), ('POSTGRES_PASSWORD', 32)):
        if len(values[key]) < minimum or not re.fullmatch(r'[A-Za-z0-9_-]+', values[key]):
            raise ValueError()
except (OSError, ValueError, UnicodeError):
    sys.exit('Ошибка: неполная, небезопасная или неподходящая серверная конфигурация; файл не заменён.')
print('Серверная конфигурация проверена, права 0600; значения не выводятся.')
PY
}

build_release_image() {
    local context=$1 release_id=$2 image="veganmedtech-server:$2"
    printf 'Локальная сборка %s (linux/amd64).\n' "$image"
    docker buildx build --load --platform linux/amd64 --provenance=false \
        --label io.veganmedtech.deployment=work0012 --tag "$image" \
        --file "$context/backend/Dockerfile" "$context"
    docker image save "$image" | gzip -1 > "$context/image.tar.gz"
    python3 - "$context" "$release_id" <<'PY'
import hashlib
import json
from pathlib import Path
import subprocess
import sys

context, version = Path(sys.argv[1]), sys.argv[2]
tag = 'veganmedtech-server:' + version
info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', tag]))[0]
if (info['Os'], info['Architecture'], info['Config']['Labels'].get('io.veganmedtech.deployment')) != ('linux', 'amd64', 'work0012'):
    sys.exit('Ошибка: неподходящие архитектура или метка локального образа.')
archive = context / 'image.tar.gz'
with archive.open('rb') as stream:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    checksum = digest.hexdigest()
# Engine ID/Size различаются между classic store и containerd Docker 29.
# Слои по digest и runtime-конфигурация задают переносимую идентичность.
keys = ('User', 'Env', 'Entrypoint', 'Cmd', 'WorkingDir', 'Labels', 'StopSignal',
        'Healthcheck', 'ExposedPorts', 'Volumes')
content = dict(rootfs=info['RootFS']['Layers'], os=info['Os'], architecture=info['Architecture'],
               config={k: info['Config'].get(k) for k in keys})
image_id = 'sha256:' + hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
manifest = dict(version=version, image_tag=tag, image_id=image_id, image_size=info['Size'],
                archive_size=archive.stat().st_size, archive_sha256=checksum)
(context / 'image.json').write_text(json.dumps(manifest) + '\n')
# Optional verified sizing metadata for the existing server's bounded RAM staging.
import tarfile
try:
    with tarfile.open(archive, 'r:gz') as saved:
        docker_manifest = json.load(saved.extractfile('manifest.json'))[0]
        config = json.load(saved.extractfile(docker_manifest['Config']))
        diffs = config['rootfs']['diff_ids']
        if diffs != info['RootFS']['Layers'] or len(diffs) != len(docker_manifest['Layers']):
            raise ValueError()
        sizes=[]
        for name, diff in zip(docker_manifest['Layers'], diffs):
            member=saved.getmember(name); digest=hashlib.sha256()
            with saved.extractfile(member) as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b''):digest.update(chunk)
            if not member.isfile() or 'sha256:'+digest.hexdigest()!=diff:raise ValueError()
            sizes.append(dict(diff_id=diff,size=member.size))
        (context/'image-layers.json').write_text(json.dumps(sizes)+'\n')
except (OSError,ValueError,KeyError,IndexError,tarfile.TarError):
    pass  # Unknown archive metadata gets the original full disk requirement.

print('Готовый образ:', info['Size'], 'байт; транспорт:', archive.stat().st_size, 'байт.')
PY
}

load_release_image() {
    python3 - "$1" "${RAM_STAGE:-0}" <<'PY'
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

release = Path(sys.argv[1])
try:
    manifest_path, archive = release / 'image.json', release / 'image.tar.gz'
    if manifest_path.is_symlink() or archive.is_symlink():
        raise ValueError()
    manifest = json.loads(manifest_path.read_text())
    expected = {'version', 'image_tag', 'image_id', 'image_size', 'archive_size', 'archive_sha256'}
    reuse = manifest.get('reuse_image')
    if set(manifest) != expected | ({'reuse_image'} if reuse else set()) or manifest['version'] != release.name:
        raise ValueError()
    if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', release.name):
        raise ValueError()
    if manifest['image_tag'] != 'veganmedtech-server:' + release.name:
        raise ValueError()
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', manifest['image_id']):
        raise ValueError()
    if any(type(manifest[k]) is not int or manifest[k] <= 0 for k in ('image_size', 'archive_size')):
        raise ValueError()
    if reuse:
        if not re.fullmatch(r'veganmedtech-server:[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', reuse) or archive.exists():
            raise ValueError()
        source = json.loads(subprocess.check_output(['docker', 'image', 'inspect', reuse]))[0]
        keys = ('User', 'Env', 'Entrypoint', 'Cmd', 'WorkingDir', 'Labels', 'StopSignal',
                'Healthcheck', 'ExposedPorts', 'Volumes')
        content = dict(rootfs=source['RootFS']['Layers'], os=source['Os'], architecture=source['Architecture'],
                       config={k: source['Config'].get(k) for k in keys})
        identity = 'sha256:' + hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if identity != manifest['image_id']:
            raise ValueError()
        subprocess.run(['docker', 'image', 'tag', reuse, manifest['image_tag']], check=True)
    else:
        if archive.stat().st_size != manifest['archive_size']:
            raise ValueError()
        with archive.open('rb') as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
            if digest.hexdigest() != manifest['archive_sha256']:
                raise ValueError()
        if sys.argv[2] == '1':
            import os, shutil, tarfile, tempfile
            sizes=json.loads((release/'image-layers.json').read_text())
            with tarfile.open(archive,'r:gz') as saved:
                exported=json.load(saved.extractfile('manifest.json'))[0]
                config=json.load(saved.extractfile(exported['Config']))
                actual=[dict(diff_id=diff,size=saved.getmember(name).size)
                        for diff,name in zip(config['rootfs']['diff_ids'],exported['Layers'])]
                if actual!=sizes:raise ValueError()
            with tempfile.TemporaryDirectory(prefix='veganmedtech-image-',dir='/dev/shm') as folder:
                staged=Path(folder)/'image.tar.gz'
                fd=os.open(staged,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as destination,archive.open('rb') as source:
                    shutil.copyfileobj(source,destination,1024*1024)
                digest=hashlib.sha256()
                with staged.open('rb') as stream:
                    for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
                if digest.hexdigest()!=manifest['archive_sha256']:raise ValueError()
                archive.unlink()
                subprocess.run(['docker','image','load','--input',str(staged)],check=True)
        else:
            subprocess.run(['docker', 'image', 'load', '--input', str(archive)], check=True)
    info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', manifest['image_tag']]))[0]
    keys = ('User', 'Env', 'Entrypoint', 'Cmd', 'WorkingDir', 'Labels', 'StopSignal',
            'Healthcheck', 'ExposedPorts', 'Volumes')
    content = dict(rootfs=info['RootFS']['Layers'], os=info['Os'], architecture=info['Architecture'],
                   config={k: info['Config'].get(k) for k in keys})
    image_id = 'sha256:' + hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (image_id, info['Os'], info['Architecture'],
        info['Config']['Labels'].get('io.veganmedtech.deployment')) != (
            manifest['image_id'], 'linux', 'amd64', 'work0012'):
        raise ValueError()
    if not reuse and archive.exists():
        archive.unlink()  # Только временный транспорт; образ/manifest/исходники остаются.
except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):
    sys.exit('Ошибка: проверка или загрузка переданного образа не выполнена; версия не запускается.')
print('Образ проверен и загружен; временный транспорт удалён, сборки на сервере нет.')
PY
}

reusable_image() {
    python3 - "$1" <<'PY'
import hashlib, json, re, subprocess, sys
from pathlib import Path
try:
    release = Path('/opt/veganmedtech/current').resolve(strict=True)
    d = json.loads((release / 'image.json').read_text())
    tag = d['image_tag']
    if not re.fullmatch(r'veganmedtech-server:[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', tag):
        raise ValueError()
    info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', tag], stderr=subprocess.DEVNULL))[0]
    keys = ('User', 'Env', 'Entrypoint', 'Cmd', 'WorkingDir', 'Labels', 'StopSignal',
            'Healthcheck', 'ExposedPorts', 'Volumes')
    content = dict(rootfs=info['RootFS']['Layers'], os=info['Os'], architecture=info['Architecture'],
                   config={k: info['Config'].get(k) for k in keys})
    identity = 'sha256:' + hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if (identity == sys.argv[1] == d['image_id'] and info['Os'] == 'linux'
            and info['Architecture'] == 'amd64'
            and info['Config']['Labels'].get('io.veganmedtech.deployment') == 'work0012'):
        print(tag)
except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
    pass  # No proven reusable image: use the full, disk-checked transfer.
PY
}

migrate_internet_environment() {
    python3 - "$1" <<'PY'
import os
from pathlib import Path
import sys
path = Path(sys.argv[1])
values = dict(line.split('=', 1) for line in path.read_text().splitlines())
values.update(APP_DEV_MODE='0', APP_TRUST_PROXY='1', APP_BASE_URL='https://94.103.3.149',
              DJANGO_ALLOWED_HOSTS='94.103.3.149,localhost,127.0.0.1')
temporary = path.with_suffix('.internet-new')
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write(''.join(f'{k}={v}\n' for k, v in values.items()))
temporary.replace(path)
print('Известная серверная конфигурация переведена в HTTPS; секреты сохранены.')
PY
}

check_proxy_paths() {
    python3 - <<'PY'
import os, socket, subprocess
from pathlib import Path
folder = Path('/etc/veganmedtech')
paths = [folder, Path('/usr/local/bin/veganmedtech-caddy'),
         Path('/etc/systemd/system/veganmedtech-proxy.service'), Path('/var/lib/veganmedtech-caddy')]
owned = False
if folder.exists() and not folder.is_symlink():
    marker = folder / '.owner'
    owned = marker.is_file() and not marker.is_symlink() and marker.read_text().strip() == 'veganmedtech-work0013-v1'
for p in paths:
    if p.is_symlink() or (p.exists() and not owned):
        raise SystemExit('Ошибка: путь proxy принадлежит неизвестной установке.')
if not owned and subprocess.run(['getent', 'passwd', 'veganmedtech-proxy'], stdout=subprocess.DEVNULL).returncode == 0:
    raise SystemExit('Ошибка: системный пользователь proxy уже существует без маркера установки.')
for p in (folder / 'Caddyfile', folder / 'proxy.env', folder / '.owner'):
    if p.is_symlink():
        raise SystemExit('Ошибка: конфигурация proxy не может быть ссылкой.')
pid = subprocess.run(['systemctl', 'show', 'veganmedtech-proxy', '-p', 'MainPID', '--value'], capture_output=True, text=True).stdout.strip()
for port in (80, 443, 8443):
    with socket.socket() as sock:
        try:
            sock.bind(('0.0.0.0', port))
        except OSError:
            listeners = subprocess.check_output(['ss', '-H', '-ltnp', f'sport = :{port}'], text=True)
            if not owned or not pid.isdigit() or pid == '0' or f'pid={pid},' not in listeners:
                raise SystemExit('Ошибка: порт HTTPS-поставки занят чужой службой.')
print('Пути, системный пользователь и порты proxy проверены.')
PY
}

ensure_mailpit_credentials() {
    python3 - "$1" "${2:-/usr/local/bin/veganmedtech-caddy}" <<'PYMAIL'
import json, os, re, stat, subprocess, sys
from pathlib import Path
path=Path(sys.argv[1])/'config/mailpit-access.json'
try:
    if path.parent.is_symlink() or Path(sys.argv[1]).is_symlink():raise ValueError()
    if path.exists() or path.is_symlink():
        info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode)!=0o600 or info.st_uid!=os.getuid():raise ValueError()
        data=json.loads(path.read_text())
    else:
        import secrets
        password=secrets.token_urlsafe(32)
        hashed=subprocess.check_output([sys.argv[2],'hash-password','--algorithm','bcrypt','--bcrypt-cost','14'],
                                       input=(password+'\n').encode(),stderr=subprocess.DEVNULL).decode().strip()
        data=dict(username='operator',password=password,password_hash=hashed)
        if not re.fullmatch(r'\$2[aby]\$14\$[./A-Za-z0-9]{53}',hashed):raise ValueError()
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:json.dump(data,stream)
    if set(data)!={'username','password','password_hash'} or data['username']!='operator':raise ValueError()
    if not isinstance(data['password'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',data['password']):raise ValueError()
    if not isinstance(data['password_hash'],str) or not re.fullmatch(r'\$2[aby]\$14\$[./A-Za-z0-9]{53}',data['password_hash']):raise ValueError()
except (OSError,ValueError,TypeError,KeyError,subprocess.CalledProcessError):
    sys.exit('Ошибка: приватные реквизиты Mailpit не прошли проверку; публикация остановлена.')
print('Реквизиты Mailpit проверены, права 0600; значения не выводятся.')
PYMAIL
}

proxy_environment() {
    local stage=${2:-production}
    [[ $stage == production || $stage == staging ]] || die 'Неизвестное TLS-окружение proxy.'
    ensure_mailpit_credentials "$1"
    python3 - "$stage" "$1" <<'PYPROXY'
import json, os, sys
from pathlib import Path
stage = sys.argv[1]
if stage not in ('production', 'staging'):
    sys.exit('Ошибка: неизвестное TLS-окружение proxy.')
ca = 'https://acme-v02.api.letsencrypt.org/directory' if stage == 'production' else 'https://acme-staging-v02.api.letsencrypt.org/directory'
hashed=json.loads((Path(sys.argv[2])/'config/mailpit-access.json').read_text())['password_hash']
target = Path('/etc/veganmedtech/proxy.env')
fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write(f'ACME_CA={ca}\nTLS_STORAGE=/var/lib/veganmedtech-caddy/{stage}\nMAILPIT_PASSWORD_HASH={hashed}\n')
print('TLS и защита Mailpit подготовлены; основной сайт без общего пароля.')
PYPROXY
    chown root:veganmedtech-proxy /etc/veganmedtech/proxy.env
}

wait_proxy() {
    local stage=${1:-production} attempt status
    local -a tls=()
    [[ $stage != staging ]] || tls=(-k) # Only the explicitly separate ACME staging test.
    for attempt in $(seq 1 90); do
        status=$(curl "${tls[@]}" --silent --output /dev/null --write-out '%{http_code}' \
            --connect-timeout 2 --max-time 4 https://94.103.3.149/ || true)
        [[ $status != 200 ]] || return 0
        sleep 2
    done
    printf 'Не подтверждён HTTPS (%s).\n' "$stage" >&2
    return 1
}

install_proxy() {
    local release=$1 base=$2 temporary
    local binary=/usr/local/bin/veganmedtech-caddy
    check_proxy_paths
    if [[ ! -e $binary ]]; then
        # Archive 18.1 MB + binary 52 MB + unchanged 256 MiB reserve.
        require_space "$base" 341835456
        temporary=$(mktemp -d "$release/caddy-download-XXXXXXXX")
        curl --fail --silent --show-error --location --proto '=https' \
            https://github.com/caddyserver/caddy/releases/download/v2.11.7/caddy_2.11.7_linux_amd64.tar.gz \
            -o "$temporary/caddy.tar.gz"
        python3 - "$temporary" <<'PY'
import hashlib, sys, tarfile
from pathlib import Path
folder = Path(sys.argv[1]); archive = folder / 'caddy.tar.gz'
if hashlib.sha256(archive.read_bytes()).hexdigest() != '727b91701a392de6ebc5027509f548bf39979e5216340d0faed8fa5e69c84f8b':
    sys.exit('Ошибка: контрольная сумма Caddy не совпала.')
with tarfile.open(archive) as stream:
    member = stream.getmember('caddy')
    if not member.isfile():
        sys.exit('Ошибка: неподходящий архив Caddy.')
    (folder / 'caddy').write_bytes(stream.extractfile(member).read())
PY
        if ! getent passwd veganmedtech-proxy >/dev/null; then
            useradd --system --home-dir /var/lib/veganmedtech-caddy --shell /usr/sbin/nologin veganmedtech-proxy
        fi
        install -d -o root -g veganmedtech-proxy -m 0750 /etc/veganmedtech
        printf '%s\n' veganmedtech-work0013-v1 > /etc/veganmedtech/.owner
        install -o root -g root -m 0755 "$temporary/caddy" "$binary"
        rm -r -- "$temporary"
    fi
    [[ $($binary version) == 'v2.11.7 '* ]] || die 'Установлена неожиданная версия Caddy.'
    install -d -o veganmedtech-proxy -g veganmedtech-proxy -m 0700 /var/lib/veganmedtech-caddy
    install -o root -g veganmedtech-proxy -m 0640 "$release/deploy/Caddyfile" /etc/veganmedtech/Caddyfile
    install -o root -g root -m 0644 "$release/deploy/veganmedtech-proxy.service" /etc/systemd/system/veganmedtech-proxy.service
    proxy_environment "$base" production
    # Validate with the explicit TLS environment; never source the configuration.
    python3 - <<'PY'
from pathlib import Path
import os, subprocess
env = dict(os.environ)
env.update(line.split('=', 1) for line in Path('/etc/veganmedtech/proxy.env').read_text().splitlines())
subprocess.run(['/usr/local/bin/veganmedtech-caddy', 'validate', '--config', '/etc/veganmedtech/Caddyfile', '--adapter', 'caddyfile'],
    env=env, user='veganmedtech-proxy', group='veganmedtech-proxy', extra_groups=[], check=True)
PY
    systemctl daemon-reload
    if [[ ! -f /etc/veganmedtech/.staging-verified ]]; then
        proxy_environment "$base" staging
        systemctl start veganmedtech-proxy
        if ! wait_proxy staging; then
            systemctl stop veganmedtech-proxy
            die 'Проверка ACME staging не пройдена; HTTP-доступ не включается.'
        fi
        printf '%s\n' 'ACME staging checked' > /etc/veganmedtech/.staging-verified
    fi
    proxy_environment "$base" production
    systemctl enable veganmedtech-proxy
    systemctl restart veganmedtech-proxy
    if ! wait_proxy production; then
        systemctl stop veganmedtech-proxy
        die 'Доверенный HTTPS не подтверждён; proxy остановлен, копии сохранены.'
    fi
    require_space "$base" 268435456
}

verify_pilot_backend() {
    python3 - "$1" <<'PYCHECK'
import hashlib, sys, urllib.request, urllib.error
from pathlib import Path
source = (Path(sys.argv[1]) / 'frontend/static/js/questionnaires.js').read_bytes()
version = hashlib.md5(source, usedforsecurity=False).hexdigest()[:12]
paths = {'/': 200, '/api/questionnaires/module': 401}
for name in ('questionnaires.js', f'questionnaires.{version}.js'):
    for suffix in ('', '.gz', '.br'):
        paths['/static/js/' + name + suffix] = 404
for path, expected in paths.items():
    request = urllib.request.Request('http://127.0.0.1:18008' + path, headers={'X-Forwarded-Proto':'https'})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    if status != expected:
        sys.exit('Ошибка: закрытая выдача опросников не подтверждена; Basic Auth не снимается.')
print('Приватный модуль и отсутствие публичных копий проверены до снятия Basic Auth.')
PYCHECK
}

verify_internet() {
    python3 - "$1" <<'PYHTTP'
import base64, json, sys, urllib.request, urllib.error
from pathlib import Path
for path in ('/', '/health/ready'):
    with urllib.request.urlopen('https://94.103.3.149' + path, timeout=10) as response:
        if response.status != 200 or response.headers.get('WWW-Authenticate'):
            raise SystemExit('Ошибка: публичный вход пилота не подтверждён.')
        if path.endswith('ready') and json.load(response).get('ready') is not True:
            raise SystemExit('Ошибка: приложение не готово.')
for path in ('/api/me', '/api/questionnaires/module'):
    try:
        urllib.request.urlopen('https://94.103.3.149' + path, timeout=10)
    except urllib.error.HTTPError as error:
        if error.code == 401 and not error.headers.get('WWW-Authenticate', '').lower().startswith('basic'):
            continue
    raise SystemExit('Ошибка: серверная авторизация пилота не подтверждена.')
data=json.loads((Path(sys.argv[1])/'config/mailpit-access.json').read_text())
for credentials,expected in [(None,401),('operator:invalid-work0015-password',401),
                             (data['username']+':'+data['password'],200)]:
    headers={}
    if credentials:headers['Authorization']='Basic '+base64.b64encode(credentials.encode()).decode()
    for path in ['/', '/api/v1/info', '/api/v1/messages']:
        try:
            with urllib.request.urlopen(urllib.request.Request('https://94.103.3.149:8443'+path,headers=headers),timeout=10) as response:
                status=response.status
        except urllib.error.HTTPError as error:status=error.code
        if status!=expected:raise SystemExit('Ошибка: защищённый HTTPS Mailpit не подтверждён.')
print('Доверенный HTTPS, вход пилота и защита Mailpit проверены.')
PYHTTP
}

can_stage_image_in_ram() {
    python3 - "$1" "${2:-/opt/veganmedtech/current}" <<'PYRAMCHECK'
import json, os, re, subprocess, sys
from pathlib import Path
try:
    proof=json.loads(sys.argv[1]); layers=proof['layers']
    if set(proof)!={'layers','image_size','archive_size'} or not isinstance(layers,list) or len(layers)<2:
        raise ValueError()
    if any(set(x)!={'diff_id','size'} or not re.fullmatch(r'sha256:[a-f0-9]{64}',x['diff_id'])
           or type(x['size']) is not int or x['size']<=0 for x in layers):raise ValueError()
    if any(type(proof[k]) is not int or proof[k]<=0 for k in ['image_size','archive_size']):raise ValueError()
    # Full-image disk allowance covers both the new raw blob and unpacked layer,
    # plus metadata/filesystem allocation. No credit for an unverified cache.
    if 2*layers[-1]['size']+16*1024*1024>proof['image_size']:raise ValueError()
    if subprocess.check_output(['docker','version','--format','{{.Server.Version}}'],text=True).strip()!='29.9.2':raise ValueError()
    lines=subprocess.check_output(['docker','info','--format','{{json .DriverStatus}}\n{{json .Containerd}}'],text=True).splitlines()
    if ['driver-type','io.containerd.snapshotter.v1'] not in json.loads(lines[0]):raise ValueError()
    daemon=json.loads(lines[1]);address=daemon['Address'];namespace=daemon['Namespaces']['Containers']
    manifest=json.loads((Path(sys.argv[2])/'image.json').read_text());tag=manifest['image_tag']
    if not re.fullmatch(r'veganmedtech-server:[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}',tag):raise ValueError()
    image=json.loads(subprocess.check_output(['docker','image','inspect',tag]))[0]
    if image['Config']['Labels'].get('io.veganmedtech.deployment')!='work0012':raise ValueError()
    prefix=[x['diff_id'] for x in layers[:-1]]
    if image['RootFS']['Layers'][:len(prefix)]!=prefix:raise ValueError()
    blobs=set(subprocess.check_output(['ctr','--address',address,'--namespace',namespace,'content','ls','-q'],text=True).split())
    if not set(prefix)<=blobs:raise ValueError()
    if not any(line.split()[1:3]==['/dev/shm','tmpfs'] for line in Path('/proc/mounts').read_text().splitlines()):raise ValueError()
    free=os.statvfs('/dev/shm');free=free.f_bavail*free.f_frsize
    available=int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:')))*1024
    if min(free,available)<3*proof['archive_size']:raise ValueError()
    print('1')
except (OSError,ValueError,KeyError,TypeError,IndexError,subprocess.CalledProcessError):
    print('0')
PYRAMCHECK
}

image_ram_proof() {
    python3 - "$1" <<'PYPROOF'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);m=json.loads((root/'image.json').read_text())
try:layers=json.loads((root/'image-layers.json').read_text())
except (OSError,ValueError):layers=[]
print(json.dumps(dict(layers=layers,image_size=m['image_size'],archive_size=m['archive_size'])))
PYPROOF
}

remote_deploy() {
    umask 077
    local release=$1 base release_id db_id snapshot old_target=''
    base=$(dirname "$(dirname "$release")"); release_id=${release##*/}
    [[ ${release%/*} == "$base/releases" && ! -L $release ]] || die 'Некорректный каталог версии.'
    [[ $(cat "$base/.owner") == veganmedtech-work0012-v1 ]] || die 'Неизвестная установка.'
    for db_id in current previous; do
        if [[ -e $base/$db_id || -L $base/$db_id ]]; then
            [[ -L $base/$db_id && $(readlink "$base/$db_id") =~ ^releases/[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$ ]] \
                || die 'Некорректная ссылка версии.'
        fi
    done
    ensure_engine
    check_server_state "$base"
    if (( INTERNET )); then
        ensure_environment "$base/config/server.env" either
        check_proxy_paths
        if [[ -e $base/config/mailpit-access.json || -L $base/config/mailpit-access.json ]]; then
            ensure_mailpit_credentials "$base"
        fi
    else
        ensure_environment "$base/config/server.env"
    fi
    local -a compose=(env -i "PATH=$PATH" "DEPLOY_IMAGE=veganmedtech-server:$release_id"
        docker compose --project-directory "$release" -p veganmedtech
        --env-file "$base/config/server.env" -f "$release/compose.yaml"
        -f "$release/compose.deploy.yaml" --profile dev)
    "${compose[@]}" config --quiet
    db_id=$("${compose[@]}" ps -a -q db)
    if docker volume inspect veganmedtech_postgres_data >/dev/null 2>&1; then
        [[ -n $db_id && $(docker inspect -f '{{.State.Running}}' "$db_id") == true ]] \
            || die 'Для копии требуется работающая прежняя БД; запустите прежнюю версию.'
    fi
    if (( RAM_STAGE )); then
        [[ $(can_stage_image_in_ram "$(image_ram_proof "$release")") == 1 ]] \
            || die 'Проверка RAM/базовых слоёв не пройдена; образ не загружается.'
    fi
    load_release_image "$release"
    "${compose[@]}" pull --quiet --policy missing db mailpit
    require_space "$base" 268435456
    if [[ -n $db_id ]]; then
        snapshot="$base/backups/$release_id.dump"
        [[ ! -e $snapshot && ! -e $snapshot.partial ]] || die 'Имя копии уже занято.'
        "${compose[@]}" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' > "$snapshot.partial"
        [[ -s $snapshot.partial ]] || die 'Получена пустая копия БД.'
        "${compose[@]}" exec -T db pg_restore --list < "$snapshot.partial" > /dev/null
        mv -- "$snapshot.partial" "$snapshot"
        printf 'Копия БД проверена: %s\n' "$snapshot"
    fi
    if (( INTERNET )); then
        cp -p -- "$base/config/server.env" "$base/backups/$release_id.env"
        for proxy_file in Caddyfile proxy.env; do
            if [[ -f /etc/veganmedtech/$proxy_file ]]; then
                cp -p -- "/etc/veganmedtech/$proxy_file" "$base/backups/$release_id-$proxy_file"
            fi
        done
        migrate_internet_environment "$base/config/server.env"
        ensure_environment "$base/config/server.env" internet
    fi
    printf 'Запуск и ожидание готовности.\n' 
    "${compose[@]}" up -d --no-build --wait --wait-timeout 180
    curl --fail --silent --show-error --max-time 5 http://127.0.0.1:18008/health/ready \
        | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ready") is True else 1)'
    if (( INTERNET )); then
        verify_pilot_backend "$release"
        install_proxy "$release" "$base"
        verify_internet "$base"
    else
        curl --fail --silent --show-error --max-time 5 http://127.0.0.1:18008/ -o /dev/null
    fi
    curl --fail --silent --show-error --max-time 5 http://127.0.0.1:18025/ -o /dev/null
    require_space "$base" 268435456
    if [[ -L $base/current ]]; then
        old_target=$(readlink "$base/current")
        ln -s -- "$old_target" "$base/.previous-$release_id"
        mv -Tf -- "$base/.previous-$release_id" "$base/previous"
    fi
    ln -s -- "releases/$release_id" "$base/.current-$release_id"
    mv -Tf -- "$base/.current-$release_id" "$base/current"
    printf 'Деплой завершён: %s.\n' "$release_id"
}

main() {
    local root mode=${1:-} release_id remote_code image_size required reuse='' identity ram_proof=''
    root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
    [[ $# -le 1 ]] || die 'Лишние аргументы; используйте --help.'
    case "$mode" in
        --help|-h)
            printf '%s\n' 'Использование: bash scripts/deploy.sh [--internet|--dry-run|--help]' \
                'Цель: root@94.103.3.149, SSH-алиас veganmedtech-server.' \
                'Нужны локальные Docker/Buildx, OpenSSH, Python 3 и настроенный вход по ключу.' \
                'Без аргументов: закрытое HTTP-демо через SSH; --internet: закрытое HTTPS-демо без туннеля.' \
                '--dry-run: только список файлов и действий, без SSH и изменений сервера.' \
                'Повтор сохраняет секреты/БД; перед обновлением создаёт закрытую копию.'
            return ;;
        --remote) require_root; remote_deploy "$root"; return ;;
        --remote-internet-ram) INTERNET=1; RAM_STAGE=1; require_root; remote_deploy "$root"; return ;;
        --remote-internet) INTERNET=1; require_root; remote_deploy "$root"; return ;;
        --internet) INTERNET=1 ;;
        --dry-run|'') ;;
        *) die 'Неизвестный аргумент; используйте --help.' ;;
    esac
    command -v python3 >/dev/null || die 'Локально нужен Python 3.'
    if [[ $mode == --dry-run ]]; then
        package_source "$root" -
        printf '%s\n' 'План: SSH veganmedtech-server → /opt/veganmedtech/releases/<версия>.' \
            'Локальная сборка → передача → проверка образа → копия БД → запуск → readiness.' \
            'SSH не выполнялся; файлы и секреты сервера не изменялись.'
        return
    fi
    command -v ssh >/dev/null || die 'Локально нужен OpenSSH.'
    command -v docker >/dev/null || die 'Локально нужен Docker.'
    docker info >/dev/null 2>&1 || die 'Локальный Docker недоступен.'
    docker buildx version >/dev/null || die 'Локально нужен Docker Buildx.'
    umask 077
    # Глобальная переменная остаётся доступна EXIT-trap после возврата main.
    package_dir=$(mktemp -d)
    trap 'rm -rf -- "$package_dir"' EXIT
    package_source "$root" "$package_dir/source.tar.gz"
    mkdir "$package_dir/context"
    tar -xzf "$package_dir/source.tar.gz" -C "$package_dir/context"
    local -a ssh=(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10
        -o ForwardAgent=no -o ClearAllForwardings=yes -o ServerAliveInterval=15
        -o ServerAliveCountMax=3 veganmedtech-server)
    "${ssh[@]}" 'command -v bash >/dev/null && command -v tar >/dev/null && command -v flock >/dev/null && test "$(id -u)" = 0 && test "$(uname -m)" = x86_64'
    release_id=$(python3 -c 'from datetime import datetime,timezone; import secrets; print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")+secrets.token_hex(4))')
    build_release_image "$package_dir/context" "$release_id"
    if (( INTERNET )); then
        identity=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["image_id"])' "$package_dir/context/image.json")
        remote_code="$(declare -f reusable_image)"$'\n'"reusable_image '$identity'"
        remote_code=${remote_code//\'/\'\\\'\'}
        reuse=$("${ssh[@]}" "bash -c '$remote_code'")
        if [[ -n $reuse ]]; then
            python3 - "$package_dir/context" "$reuse" <<'PYREUSE'
import json
from pathlib import Path
import re, sys
folder = Path(sys.argv[1]); tag = sys.argv[2]
if not re.fullmatch(r'veganmedtech-server:[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}', tag):
    sys.exit('Ошибка: некорректный результат проверки установленного образа.')
p = folder / 'image.json'; d = json.loads(p.read_text()); d['reuse_image'] = tag
p.write_text(json.dumps(d) + '\n'); (folder / 'image.tar.gz').unlink()
PYREUSE
            printf 'Проверен неизменный установленный образ; повторная передача не нужна.\n'
        fi
    fi
    tar -cf "$package_dir/release.tar" -C "$package_dir/context" .
    image_size=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["image_size"])' "$package_dir/context/image.json")
    [[ -z $reuse ]] || image_size=0
    required=$(( $(stat -c %s "$package_dir/release.tar") + image_size + 268435456 ))
    if (( INTERNET )) && [[ -z $reuse ]]; then
        local proof
        proof=$(image_ram_proof "$package_dir/context")
        remote_code="$(declare -f can_stage_image_in_ram)"$'\n'"can_stage_image_in_ram '$proof'"
        remote_code=${remote_code//\'/\'\\\'\'}
        if [[ $("${ssh[@]}" "bash -c '$remote_code'") == 1 ]]; then
            ram_proof=$proof
            local transport_size
            transport_size=$(stat -c %s "$package_dir/release.tar")
            required=$(( (image_size > transport_size ? image_size : transport_size) + 268435456 ))
            printf 'Подтверждены базовые blob и RAM: транспорт и импорт используют диск последовательно; резерв 256 MiB сохранён.\n'
        fi
    fi
    printf 'Передача версии %s; необходимый резерв с образом и транспортом: %s MiB.\n' "$release_id" "$((required / 1048576))"
    remote_code="$(declare -f die require_root require_space can_stage_image_in_ram receive_release)"$'\n'"receive_release /opt/veganmedtech '$release_id' '$required' '$INTERNET' '$ram_proof'"
    # POSIX shell quoting; JSON-экранирование для shell-команд не используется.
    remote_code=${remote_code//\'/\'\\\'\'}
    "${ssh[@]}" "bash -c '$remote_code'" < "$package_dir/release.tar"
    if (( INTERNET )); then
        printf '%s\n' 'Сайт: https://94.103.3.149 · пилот на вымышленных данных' \
            'Обычный вход в аккаунт; Mailpit оператора: https://94.103.3.149:8443/'
        return
    fi
    printf '%s\n' 'Туннель: ssh -N -L 18008:127.0.0.1:18008 -L 18025:127.0.0.1:18025 veganmedtech-server' \
        'Сайт: http://localhost:18008 · тестовая почта: http://localhost:18025'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
