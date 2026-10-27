"""Verify password-recovery limits across workers in the isolated test project."""
import argparse
import http.cookiejar
import json
from pathlib import Path
import secrets
import subprocess
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--base-url', default='http://localhost:18008')
    parser.add_argument('--output', default='/tmp/work0008-reset-limit-results.json')
    args = parser.parse_args()
    command = ['docker', 'compose', '--env-file', args.env_file, '-p', 'veganmedtech-work0008-test']
    root = Path(__file__).resolve().parents[2]

    def run(*parts):
        return subprocess.run(command + list(parts), cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.decode()

    workers = json.loads(run('exec', '-T', 'app', 'python', '-c', 'from pathlib import Path;import json;print(json.dumps([int(p) for p in Path("/proc/1/task/1/children").read_text().split()]))'))
    assert len(workers) == 2
    run('exec', '-T', 'app', 'python', 'manage.py', 'shell', '-c', 'from django.core.cache import cache;cache.clear()')
    checks = []

    def check(name, value):
        checks.append({'name': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)

    def signal(pid, name):
        run('exec', '-T', 'app', 'python', '-c', f'import os,signal;os.kill({pid},signal.SIG{name})')

    cookies = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
    opener.open(args.base_url + '/').close()

    def request():
        data = json.dumps({'email': 'unknown-' + secrets.token_hex(5) + '@example.test'}).encode()
        headers = {'Content-Type': 'application/json', 'X-CSRFToken': next(c.value for c in cookies if c.name == 'csrftoken'), 'X-Forwarded-For': '198.51.100.' + str(secrets.randbelow(200) + 1)}
        try:
            response = opener.open(urllib.request.Request(args.base_url + '/_allauth/browser/v1/auth/password/request', data, headers), timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            response.read()
            return response.status

    try:
        signal(workers[1], 'STOP')
        check('twenty recovery requests accepted on first worker', all(request() == 200 for _ in range(20)))
        signal(workers[1], 'CONT')
        signal(workers[0], 'STOP')
        check('second worker rejects recovery limit despite forged proxy', request() == 429)
    finally:
        for pid in workers:
            try:
                signal(pid, 'CONT')
            except subprocess.CalledProcessError:
                pass
    run('restart', 'app')
    run('up', '-d', '--wait', 'app')
    check('recovery limit survives application restart', request() == 429)
    result = {'passed': sum(c['passed'] for c in checks), 'failed': sum(not c['passed'] for c in checks), 'checks': checks}
    Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'failed': result['failed']}))


if __name__ == '__main__':
    main()
