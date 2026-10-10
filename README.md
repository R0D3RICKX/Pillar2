# GloBE Model Rules (Pillar Two) – navigable website

A static HTML version of the OECD GloBE Model Rules (December 2021) built from
pages 9–69 of `All.pdf`, with a stable URL for every article, paragraph and
defined term so people and AI agents (e.g. Copilot) can jump straight to a provision.

## URL scheme

| What | URL |
| --- | --- |
| Article | `/articles/3.2` |
| Paragraph | `/articles/3.2#3.2.6` (shortcut: `/3.2.6`, `/article/3.2.6`) |
| Chapter | `/chapters/5` |
| Defined term | `/definitions#qualified-iir` (shortcut: `/definitions/qualified-iir`) |
| Search / jump | `/search?q=3.2.6`, `/search?q=Qualified IIR`, `/search?q=stock-based` |
| Machine-readable | `/model-rules.json`, `/articles/3.2.json`, `/llms.txt`, `/sitemap.txt` |
| Original PDF viewer | `/viewer` |

Each article page links back to the matching page of `All.pdf` in the bundled PDF.js viewer.

## Deploying on Vercel

Import the repository in Vercel with the **Other** framework preset, no build
command and the repo root as the output directory. `vercel.json` sets clean URLs
and the shortcut redirects. Or from a terminal: `npx vercel --prod`.

## Regenerating

The HTML, JSON and `vercel.json` are generated; edit the script, not the output:

```sh
python3 scripts/build_model_rules.py   # needs poppler-utils (pdftotext, pdftohtml)
```
