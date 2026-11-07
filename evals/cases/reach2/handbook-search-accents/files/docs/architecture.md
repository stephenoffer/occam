# How findoc works

A search goes through four packages. This page follows one from the command line to the results.

## 1. Finding pages (`corpus`)

`corpus.walk.iter_paths` lists every `.md`, `.markdown` and `.txt` file under the root, sorted,
skipping hidden directories and anything in `.findocignore`. `corpus.document` reads a page, splits
off its front matter and takes the title from the front matter, the first `#` heading or the file
name, in that order. Each page also gets a digest of its bytes.

## 2. Turning text into terms (`textproc`)

`textproc.terms` splits text into words, folds each one (`textproc.normalize.fold`), drops
stopwords and applies the light stemmer (`textproc.stem`, see ADR 0002). Pages and queries go
through the same functions, so a word in a query matches the same word in a page however either
was written, within what folding and stemming cover.

## 3. The index (`indexing`)

For each page the index keeps its digest, title, tags, owner, length in terms, how many times
each term occurs and which terms are in the title (`indexing.entry.Entry`). `indexing.postings`
inverts that into term → pages when a search needs it.

`findoc reindex` (`indexing.build.update`) saves the index as JSON in `ROOT/.findoc/index.json`
(ADR 0001). It compares each page's digest with the saved entry: unchanged pages keep their
entries, new and changed pages are read again, and deleted pages are dropped. The file records a
layout number alongside the entries, and a file with a different layout is ignored.

Search never writes the index. With no usable index it reads every page into an in-memory index
(`indexing.build.scan`), which gives the same results, just more slowly.

## 4. Searching (`query`)

`query.parse` turns the search text into required terms, phrases, exclusions and `tag:` and
`title:` filters, and keeps the words as typed for highlighting. `query.search` narrows the pages
to those with every required term, applies the filters, scores what's left with BM25
(`query.rank`) and reads each result page to check phrases and build its snippet.

`textproc.snippets` picks the window of the page's text with the most query words in it and marks
each one with `**`. It works on the text as written, so the snippet shows the page as its author
wrote it.

## The command line (`findoc`)

`findoc.cli` parses arguments, `findoc.config` reads the optional `.findocrc`, and
`findoc.output` prints text or JSON.
