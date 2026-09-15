# Page-type codebook — written before any page was labelled

This defines the labels for the page-type sheet. It is committed **before** the items are
drawn and before any judgement exists, for the same reason the entailment and relevance
codebooks were: a codebook written after seeing the data is a description of the data.

## Why this sheet exists

The dereference audit asks whether a stored source URL leads a reader to the cited document.
Its destination test, `granularity()`, is a **regular expression on the final URL**. It
recognises `/issue/(view|archive)/` as an issue index and a few article-shaped patterns; and
then **everything else that answered 2xx falls through to `article_or_page`** and was counted
as "not an issue index".

A homepage passes that test. A search-results page passes it. A soft 404 — a "page not found"
served with status 200 — passes it. The audit therefore proved something narrower than the
paper claimed, and the corpus-level composite was withdrawn on 2026-09-08 partly for this
reason.

**This sheet measures how wrong the regex is.** With the labels, we can report the rule's
precision and recall against a person's reading, and either restore a corrected estimate or
state the rule's error rate as a limitation. Either outcome is publishable; the current
situation — an unvalidated regex standing in for a human judgement — is not.

## What you are judging

**One page.** You get the URL, the HTTP status, and the `<title>` the server returned when we
probed it. **Open the URL.** The title alone is not enough: a site can serve a useful title on
a useless page, and the whole point of this sheet is that machine-visible signals were
insufficient.

You do **not** see: the audit's own classification of the page, whether the URL was
issue-shaped, or how many chunks depend on it. That is deliberate — those are exactly the
things the sheet exists to check.

## Question 1 — what kind of page is it? (required)

Choose exactly one. Judge the page **as it is now**, and use `M` if it has clearly changed.

| Code | Label | Meaning |
|---|---|---|
| `D` | **document page** | A single, specific document: a journal article's landing page, a guideline, a drug label, a factsheet, a book chapter. The page is *about one thing* and that thing is identifiable from it. An abstract-only page still counts — the reader has reached the document's own page. |
| `I` | **index of many documents** | A journal issue's table of contents, an archive listing, a category page, a list of circulars. It names several documents. **Even if the cited article is one of the entries**, this is `I`: the reader has arrived at a list, not at the document. |
| `H` | **homepage or section landing** | The site's front page, or a section front ("News", "About us", "Publications") that is not a list of retrievable documents. |
| `S` | **search or browse interface** | A search-results page, a filter/browse page, a page whose content depends on a query. |
| `E` | **error served as success** | A soft 404: "page not found", "content unavailable", "this page has moved", a redirect that dumped you at an unrelated place — but the server said 200. This is the category the regex is blindest to. |
| `M` | **moved or changed beyond judgement** | The page loads but is plainly not what a 2026-09 probe saw, or the site now demands a login/consent wall you cannot get past. Use this rather than guessing. |
| `O` | **other** | None of the above. Write one line saying what it is. |

## Question 2 — is it the cited document? (required)

Only meaningful when Q1 is `D`. Answer for every item anyway; the scorer ignores the ones
where it cannot apply.

| Code | Meaning |
|---|---|
| `Y` | The page is the document the record cites — the stored title and the page agree. |
| `N` | The page is a document, but a **different** one from the stored title. |
| `?` | Cannot tell, because the **stored title is unusable** — a breadcrumb, a filename fragment, a nav label, diacritics stripped. This is a corpus defect, not a page defect, and it must not be scored as `N`. |
| `-` | Q1 is not `D`, so the question does not arise. |

Some stored titles in this corpus are known to be garbage — `Gii thiu chung Chc nng nhim v`,
`Qld vp signed`, `Văn bản > Chỉ đạo điều hành > Công văn`. When the stored title is one of
those, `?` is the correct answer, not `N`. Saying `N` there would blame the destination for an
ingestion bug, which is the exact conflation this paper is about.

## Rules

1. **Open the page.** Do not judge from the title.
2. Judge **the page reached**, not the URL's shape and not the site's general quality.
3. `I` beats `D` when both seem arguable: if the page lists several documents, it is an index
   even if one of them is the cited one.
4. `E` beats everything when the page says the content is gone, however tidily it says it.
5. A page in a language you cannot read is still judgeable for Q1 — structure is visible.
   Use `O` only if the structure itself is unclear.
6. If a page takes more than about a minute to decide, mark `O` and move on. A long deliberation
   is a signal about the instrument, not about the page.

## Sampling and what will be computed

The items are drawn from every probe that answered **2xx**, stratified by the audit's own
classification of the final URL, and the catch-all `article_or_page` bucket is deliberately
**over-sampled** because that is where the doubt lives. Stratum weights are recorded in the
key file, so the scorer post-stratifies rather than reading the sheet as one urn — the same
mistake the relevance sheet's naive 2/40 would have been.

The scorer will report:

* **precision of the regex's "not an issue index"** — of the items it called not-an-index, how
  many a person calls `D`;
* **recall** — of the items a person calls `I`, how many the regex caught;
* the share of 2xx pages that are `E`, `H` or `S` — the failure modes the regex cannot see at
  all;
* Q2 conditional on `D`, with `?` reported separately as a corpus-metadata defect.

Whatever these come to, they get reported. A rule that turns out accurate is a result; a rule
that turns out poor is a bigger one, and it is already the reason the composite was withdrawn.
