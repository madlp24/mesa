# Mesa - Working Notes for Claude

Restaurant business intelligence dashboard (Django + Chart.js). Portfolio project.
This file is auto-loaded at the start of every Claude Code session, so a new chat
knows the project without re-pasting prompts.

## Source of truth (read these first)
- GitHub repo: https://github.com/madlp24/mesa
- Project Index (user stories, sprint plan, commit convention): issue #21
- Backlog state: `gh issue list`, `gh pr list`, `git log --oneline`
- To know a story's acceptance criteria: `gh issue view <N>`

## Environment (macOS, Apple Silicon)
- Python 3.12 via Homebrew: `/opt/homebrew/opt/python@3.12/bin/python3.12`
- Virtualenv at `.venv/` (create with that python if missing)
- `gh` CLI installed and authenticated (account: madlp24)

## Common commands (run from repo root)
```bash
source .venv/bin/activate            # then `python ...` uses the venv
python manage.py runserver           # dev server (settings: config.settings.dev)
python -m pytest -q                  # tests
ruff check .                         # lint
python manage.py migrate
```
`.env` holds a local SECRET_KEY (gitignored). `db.sqlite3` is local/gitignored.

## Workflow conventions (follow exactly)
- One branch per story: `feat/usN-short-name` off `main`.
- Atomic commits, Conventional Commits style, with the GitHub issue number appended:
  `feat(catalog): add Product model #5`
- Open a PR with `Closes #N` in the body so the issue auto-closes on merge.
- Merge to `main` via PR (do not push to main directly).
- Python 3.11+ syntax, type hints where natural, PEP 8, no emojis. Run `ruff check .`
  before committing. Importer deps are added per-story as needed (already present:
  `openpyxl`, `pdfplumber` runtime; `reportlab` dev, only for PDF test fixtures).

## Status (update as work lands)
DONE + merged: US1 Scaffold (#1), US3 auth (#2/PR22), US4 logout (#3/PR23),
US5 categories (#4/PR25), US6 products (#5/PR26), US7 product detail (#6/PR27),
US8 Excel import (#7/PR28), US9 PDF import (#8/PR29), US10 skip-duplicates (#9/PR30),
US11 pluggable arch (#10/PR31). Epics catalog + ingestion are COMPLETE.

NEXT: US12 Dashboard with four headline KPIs (#11) - epic dashboard, "must".
First dashboard story; now has real data to render. Confirm with `gh issue view 11`.

### Ingestion architecture (built across US8-US11, in `sales/importers/`)
- `BaseImporter.normalize(path) -> list[CanonicalSale]` is the contract; concrete
  importers register with `@register(".ext")`; `autodiscover()` imports all
  submodules so a new format = one new file, no core edits. `get_importer_for(path)`
  dispatches by extension. Shared `rows.canonical_from_record()` does row->canonical;
  `persist()` is idempotent by `Sale.external_id` and auto-creates Product/Category
  from item catalog hints. Command: `python manage.py import_sales --file <path>`.
- DATA MODEL DECISION (Option A, agreed with user): the real POS PDF is an aggregated
  "PRODUCTOS VENDIDOS" report (per product per period, grouped by GRUPO), NOT a
  transaction list. It is mapped onto the existing Sale/SaleItem as one synthetic
  Sale+SaleItem per product per day: `external_id="<YYYY-MM-DD>:<CLAVE>"`,
  occurred_at = report period start date, CLAVE->Product.sku, GRUPO->Category,
  CANTIDAD->quantity, PRECIO VENTA PROMEDIO->unit_price, COSTO PROMEDIO->unit_cost,
  VENTA TOTAL->Sale.total. Dashboard granularity = import granularity (use DAILY PDFs).
  Real sample PDFs live on the user's Desktop (VENTA-COSTO ABRIL/JUNIO 2025), not in
  the repo; the PDF test uses a synthetic reportlab fixture that mimics the real layout.

## Known follow-ups (not blocking)
- #24 Navbar lacks a Bootstrap toggler -> logout/login hidden below 992px (mobile).
- Meat products report CANTIDAD in GRAMS (e.g. 2656), not units. Fine for revenue/margin
  but a "top products by units" view (US14/#14) would rank them oddly - rank by revenue
  or flag weight-based products when that story lands.

## Token efficiency (the user cares about this)
- Start a NEW session per user story to avoid dragging context.
- Prefer `pytest` + `curl` for verification; avoid screenshots (image tokens) and heavy
  skill loads unless visual confirmation is explicitly requested.
- Pull acceptance criteria from the GitHub issue instead of re-pasting long prompts.
