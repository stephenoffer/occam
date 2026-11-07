# Search syntax

| You type              | Pages found |
|-----------------------|-------------|
| `laptop refresh`      | containing both words, in any order |
| `"expense claim"`     | containing the words next to each other, in that order |
| `travel -visa`        | containing travel and not visa |
| `tag:office`          | tagged office (tags come from front matter) |
| `title:office`        | with office in the title |

Matching ignores case and simple English endings: `laptop` finds Laptops, `book` finds booking
and booked, `policy` finds policies. Very common words such as `the`, `and` and `how` are ignored,
so a search made only of them finds nothing.

Results are ranked with BM25, with a boost for words that appear in a page's title. Each result
shows a snippet of the page with the words you searched for in bold.
