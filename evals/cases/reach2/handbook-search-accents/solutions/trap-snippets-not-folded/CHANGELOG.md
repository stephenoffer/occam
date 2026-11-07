# Changelog

## Unreleased

- `stats --json` includes pages per owner.
- Search ignores accents, so `cafe` finds Café and `zurich` finds Zürich, and the other way round.
  Index layout 4: each clone rebuilds its index on the next reindex.

## 0.7.0 (2026-09-14)

- `title:` restricts a search to pages with the word in their title.
- `stats` shows the most common terms.
- Snippets no longer cut a word in half at either end.

## 0.6.0 (2026-06-02)

- Plurals ending in -ies are stemmed, so `policy` finds `policies`. Index layout 3: each clone
  rebuilds its index on the next reindex.
- `.findocignore` supports directory patterns ending in `/`.

## 0.5.0 (2026-03-20)

- Apostrophes are dropped when folding, so `dont` finds `don't`. Index layout 2.
- `--json` results include the page owner.

## 0.4.0 (2026-01-12)

- `reindex` only re-reads pages that changed.
- Search falls back to reading the pages when there's no index.

## 0.3.0 (2025-11-03)

- First version used outside the tools team.
