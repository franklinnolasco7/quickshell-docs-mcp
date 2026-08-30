#!/bin/sh
# Fake qs binary for offline runtime tests.
# Simulates a running quickshell instance: prints PID, waits for SIGTERM,
# cleans up, and exits.
echo "fake-qs: starting instance"
echo "fake-qs: instance id = test"
while true; do
  sleep 0.1
  echo "tick" >&2
done