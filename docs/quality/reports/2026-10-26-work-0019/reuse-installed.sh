#!/usr/bin/env bash
# WORK-0019 rev2: explicit existing-image reuse through unchanged deployment functions.
set -Eeuo pipefail
cd /home/rustiks/veganmedtech
source scripts/deploy.sh
umask 077
reuse_folder=$(mktemp -d /tmp/work0019-reuse-XXXXXXXX)
trap 'rm -rf -- "$reuse_folder"' EXIT
mkdir "$reuse_folder/context"
package_source "$PWD" "$reuse_folder/source.tar.gz"
tar -xzf "$reuse_folder/source.tar.gz" -C "$reuse_folder/context"
reuse_ssh=(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 -o ForwardAgent=no -o ClearAllForwardings=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 veganmedtech-server)
"${reuse_ssh[@]}" 'cat /opt/veganmedtech/releases/20261026T001026Z-fb8cfa65/image.json' > "$reuse_folder/original-image.json"
reuse_version=$(python3 -c 'from datetime import datetime,timezone; import secrets; print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")+secrets.token_hex(4))')
python3 - "$reuse_folder/original-image.json" "$reuse_folder/context/image.json" "$reuse_version" <<'PY'
import json,sys
from pathlib import Path
original=json.loads(Path(sys.argv[1]).read_text())
assert original['version']=='20261026T001026Z-fb8cfa65'
assert original['image_tag']=='veganmedtech-server:20261026T001026Z-fb8cfa65'
diagnostic=json.loads(Path('docs/quality/reports/2026-10-26-work-0019/reuse-diagnostic.json').read_text())
assert diagnostic['matches_manifest'] and diagnostic['manifest_identity']==original['image_id']
original['reuse_image']=original['image_tag']
original['version']=sys.argv[3]
original['image_tag']='veganmedtech-server:'+sys.argv[3]
Path(sys.argv[2]).write_text(json.dumps(original)+'\n')
PY
tar -cf "$reuse_folder/release.tar" -C "$reuse_folder/context" .
reuse_required=$(( $(stat -c %s "$reuse_folder/release.tar") + 268435456 ))
printf 'Явный проверяемый reuse %s, версия %s, необходимый резерв %s байт.\n' 'veganmedtech-server:20261026T001026Z-fb8cfa65' "$reuse_version" "$reuse_required"
reuse_remote="$(declare -f die require_root require_space can_stage_image_in_ram receive_release)"$'\n'"receive_release /opt/veganmedtech '$reuse_version' '$reuse_required' 1 ''"
reuse_remote=${reuse_remote//\'/\'\\\'\'}
"${reuse_ssh[@]}" "bash -c '$reuse_remote'" < "$reuse_folder/release.tar"
