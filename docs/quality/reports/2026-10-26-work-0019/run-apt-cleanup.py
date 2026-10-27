"""Send only the approved cleanup source and its exact manifest to the host."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
source = (ROOT / 'apt-cleanup.py').read_text()
manifest = json.loads((ROOT / 'apt-inventory.json').read_text())
ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes', 'veganmedtech-server']
payload = 'import io,sys\nsys.stdin=io.StringIO(' + repr(json.dumps(manifest)) + ')\nexec(compile(' + repr(source) + ',"approved-work0019-apt-cleanup","exec"))\n'
result = subprocess.run(ssh + ['python3 -'], input=payload.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
if result.stdout:
    (ROOT / 'apt-cleanup-result.json').write_bytes(result.stdout)
if result.stderr:
    (ROOT / 'apt-cleanup-error.txt').write_bytes(result.stderr)
result.check_returncode()
report = json.loads(result.stdout)
print(json.dumps({k: v for k, v in report.items() if k != 'removed_files'}, indent=2))
