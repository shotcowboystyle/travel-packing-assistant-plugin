# Delivery configuration

Where rendered PDFs go. Optional — without it, documents are saved to `output/` in the trip
workspace and nothing leaves the machine.

## The file

`~/.claude-plugins/travel-packing/delivery.yaml`

```yaml
default: local                 # local | email | drive | repo

email:
  to: you@example.com
  from: null                   # some providers require a verified sender

drive:
  folder: "Travel/Packing"     # never the drive root

repo:
  path: ~/repos/example/site   # a git working copy that already exists
  docs_dir: src/pages/wiki     # where the Markdown pages go
  assets_dir: public/travel    # where the PDFs go; null to skip PDFs entirely
  format: markdown+pdf         # markdown | pdf | markdown+pdf
  frontmatter:                 # merged into every generated Markdown page
    layout: ../../layouts/Wiki.astro
  commit: true
  push: false                  # see below — pushing is publishing

print: false                   # attempt a local print after rendering
```

It lives outside the plugin and outside any trip workspace on purpose:

- **Not in the plugin directory** — `/plugin update` replaces that wholesale, taking the config
  with it.
- **Not in the trip workspace** — the workspace gets committed and pushed, and an email address
  is not trip data.

Create the directory yourself; the plugin does not create it unasked.

## Email

Any available mail MCP works — the skill detects what is present rather than requiring a
specific provider. Two things matter:

**Say what is being sent, and to whom, before sending it.** Mail leaves the machine and cannot
be recalled.

**Attach by URL, not by base64, above about 100 KB.** A packing-list PDF is frequently a few
hundred kilobytes; base64ing it into tool-call arguments works but burns a large amount of
context to do it. The route that works: presign a PUT to a transient object store, upload the
file with `curl -T`, presign a GET, pass that URL as the attachment, delete the staged object
afterwards.

## Drive

Upload to the configured folder. If it does not exist, ask — do not create a folder tree
unprompted and never write to the root of a drive.

## Repo

Copies the finished documents into an existing git working copy — typically a static site, so
the packing list becomes a page you can open on a phone from anywhere rather than a PDF you
have to have downloaded.

Both forms are produced from the same YAML:

- **Markdown**, by `scripts/render_markdown.py`, into `docs_dir`. This is the useful half for a
  site: it renders as a page, the packing list works as a tick-list on a phone, and it diffs
  meaningfully between revisions.
- **PDF**, by the Typst templates, into `assets_dir`, so the printable counter card is
  reachable from the page. Set `assets_dir: null` to skip it.

File names are `packing-<trip-id>-counter-card.*` and `packing-<trip-id>-list.*`, so several
trips coexist and re-rendering the same trip overwrites its own pages rather than accumulating
copies.

`frontmatter` is merged into every generated Markdown page. Static site generators differ on
what they need — an Astro wiki page wants a `layout` and a `title`, Jekyll wants different
keys — so the plugin does not guess: whatever is in that map is emitted, plus `title` and
`generated`.

### Pushing is publishing

`push` defaults to `false` and should usually stay there.

A repo wired to a host builds on push, so pushing is a deploy, and a deploy makes the document
reachable by whoever can reach the site. **Confirm before every push** — a private repo is not
the same as a private site, and the two are easy to conflate when the repo is the thing in
front of you.

That matters more than usual for this particular document. A packing list states the dates a
home will be empty and enumerates what is worth taking from it, and a counter card names the
flights. Before the first push, establish what actually guards the deployed site — an
authenticating proxy in front of it, or nothing. If the answer is nothing, publish the counter
card if you like and keep the packing list local.

### Behaviour

1. Check `repo.path` exists and is a git working copy. If it is not, stop and say so; do not
   create it.
2. Render into `docs_dir` and `assets_dir`. Write nowhere else in that repo — no index edits,
   no navigation files, no README changes. If the site needs a link added, say so and let the
   user do it; a document-delivery step that edits a site's structure is a step that breaks the
   site.
3. Commit, when `commit: true`, with the trip id and the render date in the message.
4. Push only when `push: true` **and** the user has confirmed in this session.
5. Report the paths written, the commit, and whether anything was pushed.

## Printing

The counter card is designed to be printed: one A4 page, high contrast, status shown by both
colour and text so it survives greyscale. `print: true` attempts a local print after rendering;
if no printer is configured the skill reports that and leaves the PDF in `output/`.
