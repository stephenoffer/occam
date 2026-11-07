# findoc

Search the company handbook from a terminal.

```
$ python -m findoc search handbook expense receipt
1. Expenses  (people/expenses.md)
   **Expenses** Claim **expenses** in the finance tool within 60 days of spending the
   money. Attach a **receipt** for anything over £10; for smaller amounts a note of what
   it was for is enough. What you can claim:…
```

findoc ignores case, drops very common words and handles simple plurals and verb endings, so
`laptop`, `Laptops` and `LAPTOP` all find the laptop page. See
[docs/query-syntax.md](docs/query-syntax.md) for phrases, exclusions, `tag:` and `title:`.

## Using it

```
python -m findoc search ROOT WORDS... [--limit N] [--json]
python -m findoc reindex ROOT [--full]
python -m findoc stats ROOT [--json]
```

`ROOT` is the directory holding the pages, normally `handbook/` in this repository. Pages are
Markdown or plain text files with optional front matter (`title`, `tags`, `owner`). Anything
matched by `handbook/.findocignore` is left out.

`--json` prints `{"query": ..., "results": [{"path", "title", "owner", "score", "snippet"}]}`, which
is what the chat bot and the intranet search box use.

## Keeping it fast

Reading every page on each search is fine for a handful of pages but slow for the whole
handbook, so `findoc reindex` saves what it learned about each page under `ROOT/.findoc/`. Search
uses that when it's there and falls back to reading the pages when it isn't. `reindex` only
re-reads pages that changed since the last run, so it takes well under a second.

The whole team installs the git hook, which runs `findoc reindex handbook` after every
pull:

```
hooks/install.sh
```

The `.findoc/` directory is ignored by git; each clone has its own.

## Layout of the code

| Package     | What it does |
|-------------|--------------|
| `textproc`  | Words, folding, stopwords and stemming; snippets with matches marked |
| `corpus`    | Finding pages, front matter, reading a page |
| `indexing`  | Building, saving and loading the index |
| `query`     | Query syntax, BM25 ranking, running a search |
| `findoc`    | The command line, settings and output |

[docs/architecture.md](docs/architecture.md) follows a search through those packages.

## Development

```
python -m pytest -q
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Releases are listed in [CHANGELOG.md](CHANGELOG.md).
