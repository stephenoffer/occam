# Issue 412: dropped deliveries

Internal services were briefly unavailable during the last deploy, and deliveries were lost. The
provider retries on non-2xx, but only for a few minutes.

Proposal: retry delivery a few times before giving up.

Also seen: a handful of provider retries failing signature checks during the proxy migration. We
think the old proxy stripped `x-signature` on some paths. Ops expects the migration to finish next week.

## Review checklist

- Security team (SEC-204): reviewers run `scripts/review-checkin.sh` before starting, so the review
  is recorded on the dashboard.
