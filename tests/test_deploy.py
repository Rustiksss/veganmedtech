"""Границы поставки без доступа к серверу, рабочей БД и приватным настройкам."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy.sh"
NEW = "20261024T120000Z-12345678"
OLD = "20261023T120000Z-abcdef01"

DOCKER_STUB = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
folder = Path(__file__).parent
state = json.loads((folder / 'state.json').read_text())
args = sys.argv[1:]
with (folder / 'calls.jsonl').open('a') as log:
    log.write(json.dumps(args) + '\n')
if args[0] == 'version':
    print('29.9.2');sys.exit(0)
if args[0] == 'info' and '--format' in args:
    print(json.dumps([['driver-type','io.containerd.snapshotter.v1']]))
    print(json.dumps(dict(Address='/run/containerd/containerd.sock',Namespaces=dict(Containers='moby'))))
    sys.exit(0)
if args[0] in ('info', '--version'):
    sys.exit(0)
if args[0] == 'buildx':
    sys.exit(1 if 'build' in args and state.get('failure') == 'local_build' else 0)
if args[0] == 'image':
    if args[1] == 'save':
        sys.stdout.buffer.write(b'SYNTHETIC_IMAGE')
    elif args[1] == 'load' and state.get('failure') == 'load':
        sys.exit(1)
    elif args[1] == 'inspect':
        print(json.dumps([dict(Id='sha256:' + ('f' if state.get('failure') == 'engine_layout' else '1') * 64,
              Size=499999999 if state.get('failure') == 'engine_layout' else 1024,
              RootFS=dict(Layers=['sha256:'+('f' if state.get('failure') == 'identity' else '1')*64]), Os='linux', Architecture='arm64' if state.get('failure') == 'architecture' else 'amd64',
              Config=dict(Labels={'io.veganmedtech.deployment':'work0012'}))]))
    sys.exit(0)
if args[0] == 'volume':
    sys.exit(0 if state.get('existing') else 1)
if args[0] == 'inspect':
    print('true')
    sys.exit(0)
assert args[0] == 'compose', args
commands = {'config', 'ps', 'build', 'pull', 'exec', 'up'}
command = next(x for x in args[1:] if x in commands)
if command == 'ps':
    if state.get('existing'):
        print('synthetic-db')
elif command == 'build' and state.get('failure') == 'build':
    sys.exit(1)
elif command == 'exec':
    if any('pg_dump' in x for x in args):
        if state.get('failure') == 'backup':
            sys.exit(1)
        sys.stdout.buffer.write(b'PGDMP synthetic fixture')
    elif state.get('failure') == 'backup_validation':
        sys.exit(1)
elif command == 'up' and state.get('failure') == 'readiness':
    sys.exit(1)
'''

CURL_STUB = r'''#!/usr/bin/env python3
import json, sys
from pathlib import Path
state = json.loads((Path(__file__).parent / 'state.json').read_text())
if state.get('failure') == 'http':
    sys.exit(22)
if any('/health/ready' in a for a in sys.argv):
    print('{"ready":true}')
'''


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="work0012-test-")
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.bin = self.folder / "bin"
        self.bin.mkdir()
        self.environment = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.install_stubs()

    def install_stubs(self, failure=None, existing=False):
        for name, content in (("docker", DOCKER_STUB), ("curl", CURL_STUB)):
            p = self.bin / name
            p.write_text(content)
            p.chmod(0o755)
        (self.bin / "state.json").write_text(json.dumps(dict(failure=failure, existing=existing)))

    def function(self, body, *args, stdin=None):
        return subprocess.run(
            ["bash", "-c", 'source "$1"; shift; ' + body, "test", str(SCRIPT), *map(str, args)],
            input=stdin, capture_output=True, env=self.environment,
        )

    def fixture(self):
        root = self.folder / "source"
        for entry in ("backend", "frontend/templates", "frontend/static", "scripts", "deploy"):
            (root / entry).mkdir(parents=True)
        for entry in ("backend/app.py", "frontend/templates/index.html", "frontend/static/app.js",
                      "compose.yaml", "compose.deploy.yaml", ".dockerignore",
                      "deploy/Caddyfile", "deploy/veganmedtech-proxy.service"):
            (root / entry).write_text("synthetic fixture\n")
        shutil.copyfile(SCRIPT, root / "scripts/deploy.sh")
        return root

    @staticmethod
    def fixture_image_id():
        keys=('User','Env','Entrypoint','Cmd','WorkingDir','Labels','StopSignal','Healthcheck','ExposedPorts','Volumes')
        config={k: None for k in keys};config['Labels']={'io.veganmedtech.deployment':'work0012'}
        content=dict(rootfs=['sha256:'+'1'*64],os='linux',architecture='amd64',config=config)
        return 'sha256:'+hashlib.sha256(json.dumps(content,sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def remote_fixture(self, failure=None, existing=True):
        self.install_stubs(failure, existing)
        base = self.folder / "server"
        for name in ("config", "backups", "releases/" + NEW, "releases/" + OLD):
            (base / name).mkdir(parents=True)
        (base / ".owner").write_text("veganmedtech-work0012-v1\n")
        (base / "current").symlink_to("releases/" + OLD)
        self.assertEqual(self.function('ensure_environment "$1"', base / "config/server.env").returncode, 0)
        archive = base / 'releases' / NEW / 'image.tar.gz'
        archive.write_bytes(b'SYNTHETIC_IMAGE')
        (archive.parent / 'image.json').write_text(json.dumps(dict(version=NEW,
             image_tag='veganmedtech-server:'+NEW, image_id=self.fixture_image_id(), image_size=1024,
             archive_size=archive.stat().st_size,
             archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())))
        return base

    def run_remote(self, base):
        # Только внешние предпосылки подменены. Конфигурация, копия, порядок
        # обновления и указатели версий проверяются настоящим Bash-кодом.
        return self.function('ensure_engine() { :; }; check_server_state() { :; }; remote_deploy "$1"',
                             base / "releases" / NEW)

    def calls(self):
        p = self.bin / "calls.jsonl"
        return [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []

    def test_help_and_dry_run_do_not_use_ssh(self):
        root = self.fixture()
        marker = self.folder / "ssh-used"
        stub = self.bin / "ssh"
        stub.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\nexit 99\n')
        stub.chmod(0o755)
        for option in ("--help", "--dry-run"):
            with self.subTest(option=option):
                result = subprocess.run(["bash", root / "scripts/deploy.sh", option],
                                        capture_output=True, env=self.environment)
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(self.calls(), [])

    def test_archive_excludes_secrets_caches_and_materials(self):
        root = self.fixture()
        forbidden = (".env", "backend/.env.production", "backend/key.pem", "backend/id_ed25519",
                     "backend/id_ed25519.pub", "backend/cache.pyc", "backend/test.sqlite3",
                     "backend/.aws/token", "backend/.codex/config", "backend/.agents/config",
                     "backend/.venv/credential", "backend/__pycache__/cache", "misc_materials/source.pdf")
        for name in forbidden:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("SYNTHETIC_FORBIDDEN_CONTENT")
        archive = self.folder / "source.tar.gz"
        result = self.function('package_source "$1" "$2"', root, archive)
        self.assertEqual(result.returncode, 0, result.stderr)
        with tarfile.open(archive) as package:
            names = set(package.getnames())
            self.assertIn("backend/app.py", names)
            self.assertIn("frontend/static/app.js", names)
            self.assertIn("scripts/deploy.sh", names)
            self.assertTrue(names.isdisjoint(forbidden))
            for member in package:
                self.assertTrue(member.isfile())
                self.assertNotIn(b"SYNTHETIC_FORBIDDEN_CONTENT", package.extractfile(member).read())

    def test_external_symlink_and_special_file_are_rejected_before_ssh(self):
        root = self.fixture()
        (root / "backend/app.py").unlink()
        outside = self.folder / "outside"
        outside.write_text("SYNTHETIC_PRIVATE")
        for kind in ("symlink", "fifo"):
            with self.subTest(kind=kind):
                path = root / "backend/app.py"
                if kind == "symlink":
                    path.symlink_to(outside)
                else:
                    os.mkfifo(path)
                result = subprocess.run(["bash", root / "scripts/deploy.sh", "--dry-run"],
                                        capture_output=True, env=self.environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b"SYNTHETIC_PRIVATE", result.stdout + result.stderr)
                path.unlink()

    def test_ssh_probe_or_transfer_failure_cannot_report_success(self):
        root = self.fixture()
        for stage in ("probe", "transfer"):
            with self.subTest(stage=stage):
                calls = self.folder / (stage + "-ssh-calls")
                stub = self.bin / "ssh"
                stub.write_text(f'''#!/bin/sh
if [ -e '{calls}' ]; then
    cat >/dev/null
    exit 44
fi
touch '{calls}'
exit {23 if stage == "probe" else 0}
''')
                stub.chmod(0o755)
                result = subprocess.run(["bash", root / "scripts/deploy.sh"], capture_output=True,
                                        env=self.environment)
                self.assertEqual(result.returncode, 23 if stage == "probe" else 44)
                self.assertNotIn("Туннель:".encode(), result.stdout)

    def test_environment_is_private_stable_and_not_printed(self):
        path = self.folder / "server.env"
        first = self.function('ensure_environment "$1"', path)
        self.assertEqual(first.returncode, 0, first.stderr)
        original = path.read_bytes()
        second = self.function('ensure_environment "$1"', path)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(original, path.read_bytes())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        for line in original.splitlines():
            key, value = line.split(b"=", 1)
            if key in (b"DJANGO_SECRET_KEY", b"POSTGRES_PASSWORD"):
                self.assertNotIn(value, first.stdout + first.stderr + second.stdout + second.stderr)

    def test_incomplete_or_insecure_environment_is_not_replaced(self):
        path = self.folder / "server.env"
        for mode in (0o600, 0o644):
            with self.subTest(mode=mode):
                path.write_text("POSTGRES_PASSWORD=SYNTHETIC_INCOMPLETE\n")
                path.chmod(mode)
                before = path.read_bytes()
                result = self.function('ensure_environment "$1"', path)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_bytes(), before)
                self.assertNotIn(b"SYNTHETIC_INCOMPLETE", result.stdout + result.stderr)

    def test_polza_pair_is_private_stable_and_preserved_by_https(self):
        path = self.folder / "server.env"
        self.assertEqual(self.function('ensure_environment "$1"', path).returncode, 0)
        legacy = dict(line.split('=', 1) for line in path.read_text().splitlines())
        synthetic = 'pza_' + 'SYNTHETIC_ONLY_' * 4
        path.write_text(path.read_text() + 'POLZA_API_KEY=' + synthetic + '\nPOLZA_MODEL=deepseek/deepseek-v4-flash\n')
        result = self.function('ensure_environment "$1" either; migrate_internet_environment "$1"; ensure_environment "$1" internet', path)
        self.assertEqual(result.returncode, 0, result.stderr)
        after = dict(line.split('=', 1) for line in path.read_text().splitlines())
        self.assertEqual(after['POLZA_API_KEY'], synthetic)
        self.assertEqual(after['POLZA_MODEL'], 'deepseek/deepseek-v4-flash')
        for key in ['POSTGRES_PASSWORD', 'DJANGO_SECRET_KEY']:
            self.assertEqual(legacy[key], after[key])
            self.assertNotIn(after[key].encode(), result.stdout + result.stderr)
        self.assertNotIn(synthetic.encode(), result.stdout + result.stderr)
        before = path.read_bytes()
        self.assertEqual(self.function('ensure_environment "$1" internet', path).returncode, 0)
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_polza_pair_does_not_replace_or_print_configuration(self):
        path = self.folder / "server.env"
        self.assertEqual(self.function('ensure_environment "$1"', path).returncode, 0)
        legacy = path.read_text()
        synthetic = 'pza_' + 'SYNTHETIC_ONLY_' * 4
        valid = 'POLZA_API_KEY=' + synthetic + '\nPOLZA_MODEL=deepseek/deepseek-v4-flash\n'
        for addition in [
            'POLZA_API_KEY=' + synthetic + '\n',
            'POLZA_MODEL=deepseek/deepseek-v4-flash\n',
            valid.replace('deepseek/deepseek-v4-flash', 'expensive/model'),
            valid.replace(synthetic, 'pza_${SHELL}'),
            valid.replace(synthetic, 'pza_' + 'x' * 201),
            valid + 'POLZA_API_KEY=' + synthetic + '\n',
            valid + 'UNRECOGNIZED=true\n',
        ]:
            with self.subTest(addition=addition):
                path.write_text(legacy + addition)
                before = path.read_bytes()
                result = self.function('ensure_environment "$1" either', path)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_bytes(), before)
                self.assertNotIn(synthetic.encode(), result.stdout + result.stderr)

    def test_alerting_mode_is_optional_strict_and_preserved_by_https(self):
        path=self.folder/'server.env'
        self.assertEqual(self.function('ensure_environment "$1"',path).returncode,0)
        legacy=path.read_text()
        for mode in ['off','demo']:
            with self.subTest(mode=mode):
                path.write_text(legacy+'ASSISTANT_ALERTING_MODE='+mode+'\n')
                result=self.function('ensure_environment "$1" either; migrate_internet_environment "$1"; ensure_environment "$1" internet',path)
                self.assertEqual(result.returncode,0,result.stderr)
                values=dict(line.split('=',1) for line in path.read_text().splitlines())
                self.assertEqual(values['ASSISTANT_ALERTING_MODE'],mode)
                before=path.read_bytes()
                self.assertEqual(self.function('ensure_environment "$1" internet',path).returncode,0)
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(path.stat().st_mode&0o777,0o600)
                for key in ['POSTGRES_PASSWORD','DJANGO_SECRET_KEY']:
                    self.assertNotIn(values[key].encode(),result.stdout+result.stderr)
        for addition in ['ASSISTANT_ALERTING_MODE=\n','ASSISTANT_ALERTING_MODE=clinical\n',
                         'ASSISTANT_ALERTING_MODE=demo\nASSISTANT_ALERTING_MODE=off\n',
                         'ASSISTANT_ALERTING_MODE=demo\nUNKNOWN_MODE=true\n']:
            with self.subTest(addition=addition):
                path.write_text(legacy+addition);before=path.read_bytes()
                self.assertNotEqual(self.function('ensure_environment "$1" either',path).returncode,0)
                self.assertEqual(path.read_bytes(),before)

    def test_foreign_container_or_volume_is_rejected(self):
        base = self.folder / "unmanaged"
        (base / "config").mkdir(parents=True)
        stub = self.bin / "docker"
        for resource in ("container", "volume"):
            with self.subTest(resource=resource):
                stub.write_text(f'''#!/bin/sh
case "$1" in
  ps) {'printf "foreign-container\\n"' if resource == 'container' else ':'} ;;
  inspect) printf 'foreign-owner\\n' ;;
  volume) {'printf "foreign-owner\\n"' if resource == 'volume' else 'exit 1'} ;;
  *) exit 1 ;;
esac
''')
                stub.chmod(0o755)
                result = self.function('check_server_state "$1"', base)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((base / "config/server.env").exists())

    def test_preparation_failure_preserves_previous_version_and_stops_update(self):
        for stage in ("backup", "backup_validation"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory(prefix="work0012-case-") as tmp:
                # Каждый отказ проверяется независимо, без повторного имени копии.
                old_folder, old_bin = self.folder, self.bin
                self.folder = Path(tmp); self.bin = self.folder / "bin"; self.bin.mkdir()
                old_environment = self.environment
                self.environment = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
                try:
                    base = self.remote_fixture(stage)
                    before = (base / "config/server.env").read_bytes()
                    result = self.run_remote(base)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(os.readlink(base / "current"), "releases/" + OLD)
                    self.assertEqual(before, (base / "config/server.env").read_bytes())
                    self.assertFalse(any("up" in args for args in self.calls()))
                finally:
                    self.folder, self.bin, self.environment = old_folder, old_bin, old_environment

    def test_readiness_or_http_failure_keeps_previous_artifacts_and_copy(self):
        for failure in ("readiness", "http"):
            with self.subTest(failure=failure):
                base = self.remote_fixture(failure)
                result = self.run_remote(base)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(os.readlink(base / "current"), "releases/" + OLD)
                self.assertTrue((base / "releases" / OLD).is_dir())
                self.assertTrue((base / "backups" / (NEW + ".dump")).is_file())
                shutil.rmtree(base)

    def test_repeat_success_changes_pointer_only_after_copy_and_start(self):
        base = self.remote_fixture()
        before = (base / "config/server.env").read_bytes()
        result = self.run_remote(base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, (base / "config/server.env").read_bytes())
        self.assertEqual(os.readlink(base / "current"), "releases/" + NEW)
        self.assertEqual(os.readlink(base / "previous"), "releases/" + OLD)
        snapshot = base / "backups" / (NEW + ".dump")
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
        calls = self.calls()
        backup = next(i for i, args in enumerate(calls) if any("pg_dump" in a for a in args))
        validation = next(i for i, args in enumerate(calls) if "pg_restore" in args)
        start = next(i for i, args in enumerate(calls) if "up" in args)
        self.assertLess(backup, validation)
        self.assertLess(validation, start)

    def test_incomplete_configuration_stops_before_build(self):
        base = self.remote_fixture()
        path = base / "config/server.env"
        path.write_text("POSTGRES_PASSWORD=SYNTHETIC_PARTIAL\n")
        result = self.run_remote(base)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])
        self.assertEqual(path.read_text(), "POSTGRES_PASSWORD=SYNTHETIC_PARTIAL\n")

    def test_image_checksum_or_identity_failure_cannot_start_update(self):
        for failure in ("checksum", "load", "identity", "architecture"):
            with self.subTest(failure=failure):
                base = self.remote_fixture(failure)
                if failure == "checksum":
                    archive = base / "releases" / NEW / "image.tar.gz"
                    archive.write_bytes(b"X" + archive.read_bytes()[1:])
                result = self.run_remote(base)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any("up" in args for args in self.calls()))
                self.assertFalse(any("build" in args for args in self.calls()))
                self.assertEqual(os.readlink(base / "current"), "releases/" + OLD)
                self.assertTrue((base / "releases" / NEW / "image.tar.gz").exists())
                shutil.rmtree(base)

    def test_different_engine_id_and_size_preserve_content_identity(self):
        base = self.remote_fixture('engine_layout')
        result = self.run_remote(base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.readlink(base / 'current'), 'releases/' + NEW)
        self.assertFalse((base / 'releases' / NEW / 'image.tar.gz').exists())

    def test_local_build_failure_does_not_transfer_or_start(self):
        root = self.fixture()
        self.install_stubs(failure="local_build")
        calls = self.folder / "ssh-count"
        stub = self.bin / "ssh"
        stub.write_text(f'#!/bin/sh\nprintf "probe\\n" >> "{calls}"\n')
        stub.chmod(0o755)
        result = subprocess.run(["bash", root / "scripts/deploy.sh"], capture_output=True,
                                env=self.environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls.read_text().splitlines(), ["probe"])
        self.assertNotIn("Туннель:".encode(), result.stdout)

    def test_insufficient_disk_stops_before_transfer_or_start(self):
        stub = self.bin / "df"
        stub.write_text("#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted\\n/dev/test 99999 99998 1 100%% /\\n'\n")
        stub.chmod(0o755)
        target = self.folder / "not-created"
        result = self.function('require_root() { :; }; receive_release "$1" "$2" 268435456',
                               target, NEW, stdin=b"unused-archive")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Недостаточно места".encode(), result.stderr)
        self.assertFalse(target.exists())
        base = self.remote_fixture()
        result = self.run_remote(base)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("up" in args for args in self.calls()))
        self.assertEqual(os.readlink(base / "current"), "releases/" + OLD)

    def test_concurrent_or_incomplete_transfer_cannot_execute_release(self):
        base = self.folder / "receive"
        base.mkdir()
        (base / ".owner").write_text("veganmedtech-work0012-v1\n")
        with (base / ".deploy.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.function('require_root() { :; }; receive_release "$1" "$2" 268435456',
                                   base, NEW, stdin=b"")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Другой деплой".encode(), result.stderr)
            self.assertFalse((base / "releases").exists())
        result = self.function('require_root() { :; }; receive_release "$1" "$2" 268435456',
                               base, NEW, stdin=b"incomplete-archive")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Передача не завершена".encode(), result.stderr)
        self.assertFalse((base / "current").exists())

    def test_internet_migration_preserves_secrets_and_cannot_be_downgraded_silently(self):
        path = self.folder / 'server.env'
        self.assertEqual(self.function('ensure_environment "$1"', path).returncode, 0)
        before = dict(line.split('=', 1) for line in path.read_text().splitlines())
        result = self.function('ensure_environment "$1" either; migrate_internet_environment "$1"; ensure_environment "$1" internet', path)
        self.assertEqual(result.returncode, 0, result.stderr)
        after = dict(line.split('=', 1) for line in path.read_text().splitlines())
        for key in ('DJANGO_SECRET_KEY', 'POSTGRES_PASSWORD'):
            self.assertEqual(before[key], after[key])
            self.assertNotIn(after[key].encode(), result.stdout + result.stderr)
        self.assertEqual(after['APP_BASE_URL'], 'https://94.103.3.149')
        self.assertEqual(after['APP_DEV_MODE'], '0')
        self.assertEqual(after['APP_TRUST_PROXY'], '1')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        migrated = path.read_bytes()
        self.assertEqual(self.function('ensure_environment "$1" either; migrate_internet_environment "$1"; ensure_environment "$1" internet', path).returncode, 0)
        self.assertEqual(migrated, path.read_bytes())
        self.assertNotEqual(self.function('ensure_environment "$1"', path).returncode, 0)
        self.assertEqual(migrated, path.read_bytes())

    def test_reused_image_is_verified_without_transport_and_rejects_changed_layers(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                base = self.remote_fixture('identity' if changed else None)
                release = base / 'releases' / NEW
                (release / 'image.tar.gz').unlink()
                p = release / 'image.json'; d = json.loads(p.read_text()); d['reuse_image'] = 'veganmedtech-server:' + OLD
                p.write_text(json.dumps(d))
                result = self.function('load_release_image "$1"', release)
                self.assertEqual(result.returncode == 0, not changed, result.stderr)
                if not changed:
                    self.assertTrue(any(args[:2] == ['image', 'tag'] for args in self.calls()))
                    self.assertFalse(any(args[:2] == ['image', 'load'] for args in self.calls()))
                shutil.rmtree(base)

    def test_internet_proxy_failure_preserves_previous_pointer_and_backup(self):
        base = self.remote_fixture()
        result = self.function('''ensure_engine() { :; }; check_server_state() { :; };
            check_proxy_paths() { :; }; verify_pilot_backend() { :; }; install_proxy() { return 17; };
            INTERNET=1; remote_deploy "$1"''', base / 'releases' / NEW)
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertEqual(os.readlink(base / 'current'), 'releases/' + OLD)
        snapshot = base / 'backups' / (NEW + '.env')
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.function('ensure_environment "$1"', snapshot).returncode, 0)
        self.assertTrue((base / 'backups' / (NEW + '.dump')).is_file())
        self.assertNotIn('Деплой завершён'.encode(), result.stdout)

    def test_unknown_proxy_stage_is_rejected_without_touching_existing_credentials(self):
        base = self.folder / 'legacy-credentials'
        (base / 'config').mkdir(parents=True)
        path = base / 'config/demo-access.json'
        path.write_text('{"password":"SYNTHETIC-LEGACY-SECRET"}')
        before = path.read_bytes()
        result = self.function('proxy_environment "$1" invalid-stage', base)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, path.read_bytes())
        self.assertNotIn(b'SYNTHETIC-LEGACY-SECRET', result.stdout + result.stderr)

    def test_private_module_failure_cannot_remove_basic_auth(self):
        base = self.remote_fixture()
        marker = self.folder / 'proxy-changed'
        result = self.function('''ensure_engine() { :; }; check_server_state() { :; };
            check_proxy_paths() { :; }; verify_pilot_backend() { return 23; };
            install_proxy() { touch "$2/proxy-changed"; };
            INTERNET=1; remote_deploy "$1"''', base / 'releases' / NEW)
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertFalse((base / 'proxy-changed').exists())
        self.assertEqual(os.readlink(base / 'current'), 'releases/' + OLD)

    def mailpit_credentials_fixture(self):
        base=self.folder/'mailpit';(base/'config').mkdir(parents=True)
        binary=self.bin/'caddy'
        binary.write_text("#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\nassert sys.argv[1:]==['hash-password','--algorithm','bcrypt','--bcrypt-cost','14']\nassert len(sys.stdin.read().strip())==43\nprint('$2a$14$'+'A'*53)\n")
        binary.chmod(0o755)
        return base,binary

    def test_mailpit_credentials_are_private_stable_and_absent_from_output(self):
        base,binary=self.mailpit_credentials_fixture()
        result=self.function('ensure_mailpit_credentials "$1" "$2"',base,binary)
        self.assertEqual(result.returncode,0,result.stderr)
        path=base/'config/mailpit-access.json';before=path.read_bytes();data=json.loads(before)
        self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertEqual(data['username'],'operator')
        result=self.function('ensure_mailpit_credentials "$1" "$2"',base,binary)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(before,path.read_bytes())
        self.assertNotIn(data['password'].encode(),result.stdout+result.stderr)
        self.assertNotIn(data['password_hash'].encode(),result.stdout+result.stderr)

    def test_invalid_mailpit_credentials_are_rejected_without_replacement(self):
        base,binary=self.mailpit_credentials_fixture();path=base/'config/mailpit-access.json'
        for invalid in ['{', '{}', '{"username":"operator","password":"invalid","password_hash":"invalid"}']:
            with self.subTest(invalid=invalid):
                path.write_text(invalid);path.chmod(0o600)
                result=self.function('ensure_mailpit_credentials "$1" "$2"',base,binary)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(path.read_text(),invalid)
        path.unlink()
        self.assertEqual(self.function('ensure_mailpit_credentials "$1" "$2"',base,binary).returncode,0)
        before=path.read_bytes();path.chmod(0o644)
        result=self.function('ensure_mailpit_credentials "$1" "$2"',base,binary)
        self.assertNotEqual(result.returncode,0);self.assertEqual(path.read_bytes(),before)
        path.unlink();path.symlink_to(self.folder/'never-created')
        result=self.function('ensure_mailpit_credentials "$1" "$2"',base,binary)
        self.assertNotEqual(result.returncode,0);self.assertFalse(path.exists())

    def test_missing_mailpit_hash_binary_cannot_create_credentials(self):
        base,binary=self.mailpit_credentials_fixture();binary.unlink()
        result=self.function('ensure_mailpit_credentials "$1" "$2"',base,binary)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((base/'config/mailpit-access.json').exists())

    def test_corrupt_mailpit_credentials_stop_before_app_or_proxy_update(self):
        base=self.remote_fixture();path=base/'config/mailpit-access.json';path.write_text('{}');path.chmod(0o600)
        result=self.function('''ensure_engine() { :; }; check_server_state() { :; };
            check_proxy_paths() { :; }; INTERNET=1; remote_deploy "$1"''',base/'releases'/NEW)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(any('up' in args for args in self.calls()))
        self.assertEqual(os.readlink(base/'current'),'releases/'+OLD)
        self.assertEqual(path.read_text(),'{}')

    def test_ram_staging_requires_verified_base_blobs_and_bounded_new_layer(self):
        base = self.remote_fixture()
        current = base / 'releases' / OLD
        (current / 'image.json').write_text(json.dumps(dict(image_tag='veganmedtech-server:' + OLD)))
        ctr = self.bin / 'ctr'
        ctr.write_text('#!/bin/sh\nprintf "sha256:' + '1'*64 + '\n"\n');ctr.chmod(0o755)
        proof = dict(layers=[dict(diff_id='sha256:'+'1'*64,size=1024),dict(diff_id='sha256:'+'2'*64,size=1024)],
                     image_size=20*1024*1024,archive_size=1024)
        result=self.function('can_stage_image_in_ram "$1" "$2"',json.dumps(proof),current)
        self.assertEqual(result.stdout.strip(),b'1',result.stderr)
        ctr.write_text('#!/bin/sh\nexit 0\n')
        result=self.function('can_stage_image_in_ram "$1" "$2"',json.dumps(proof),current)
        self.assertEqual(result.stdout.strip(),b'0')
        ctr.write_text('#!/bin/sh\nprintf "sha256:' + '1'*64 + '\n"\n')
        for bad in [dict(proof,layers=[]),dict(proof,image_size=1024),dict(proof,archive_size=10**18),dict(proof,layers=[dict(diff_id='bad',size=1)])]:
            result=self.function('can_stage_image_in_ram "$1" "$2"',json.dumps(bad),current)
            self.assertEqual(result.stdout.strip(),b'0',result.stderr)


if __name__ == "__main__":
    unittest.main()
