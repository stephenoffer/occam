#!/usr/bin/env bash
# Cron entry point on the clinic server. See docs/runbook.md.
set -euo pipefail

DB="${KESTREL_DB:-/srv/kestrel/clinic.db}"
cd "$(dirname "$0")/.."

case "${1:-}" in
  charges)   python3 -m billing --db "$DB" run ;;
  reminders) python3 -m messaging --db "$DB" reminders ;;
  monthly)   python3 -m reports --db "$DB" monthly --month "$(date -d 'last month' +%Y-%m)" ;;
  *) echo "usage: $0 charges|reminders|monthly" >&2; exit 2 ;;
esac
