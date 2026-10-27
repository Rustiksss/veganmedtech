source /tmp/deploy.sh
mkdir -p /etc/veganmedtech
if output=$(check_proxy_paths 2>&1); then exit 1; fi
[[ $output == *'принадлежит неизвестной установке'* ]]
rmdir /etc/veganmedtech
mkdir -p /tmp/stubs
printf '#!/bin/sh\nprintf "0\\n"\n' > /tmp/stubs/systemctl
printf '#!/bin/sh\nprintf "LISTEN users: pid=999,fd=1\\n"\n' > /tmp/stubs/ss
chmod +x /tmp/stubs/systemctl /tmp/stubs/ss
export PATH=/tmp/stubs:$PATH
python -c 'import socket,time;s=socket.socket();s.bind(("0.0.0.0",80));s.listen();time.sleep(20)' &
listener=$!
trap 'kill "$listener" 2>/dev/null || true' EXIT
sleep 0.5
if output=$(check_proxy_paths 2>&1); then exit 1; fi
[[ $output == *'занят чужой службой'* ]]
printf 'Foreign proxy path rejected; foreign occupied port rejected; 2 checks passed.\n'
