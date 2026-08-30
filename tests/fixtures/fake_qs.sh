#!/bin/sh
# Fake qs binary for offline runtime tests.
# - `qs -p <entrypoint>` simulates a running quickshell instance (loops).
# - `qs ipc ...` simulates an IPC call to a missing target: no stdout, exit 1.
if [ "$1" = "ipc" ]; then
  echo "error: no such target" >&2
  exit 1
fi
echo "fake-qs: starting instance"
echo "fake-qs: instance id = test"
while true; do
  sleep 0.1
done