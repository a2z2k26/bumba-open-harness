#!/bin/bash
# Stop hook: Enforce session summary writing.
# Warning mode — logs a reminder.

input=$(cat)
timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "[${timestamp}] Memory Hygiene: Agent session ending — check for summary" >> /tmp/bumba-memory-hygiene.log
