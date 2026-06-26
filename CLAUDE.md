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
US11 pluggable arch (#10/PR31), US12 dashboard KPIs (#11/PR32),
US13 date-range default (#12/PR33), US14 revenue line chart (#13/PR34),
US15 top-products bar (#14/PR35), US16 revenue-by-category doughnut (#15/PR36),
US17 margin analysis page (#16/PR37), US18 monthly P&L (#17/PR38),
US20 test coverage + CI (#18/PR40), navbar toggler fix (#24/PR39),
UI visual refresh (PR42), US2 onboarding (#19/PR43), US21 bilingual EN/ES (#41/PR44).
Epics catalog, ingestion, dashboard and analysis are COMPLETE.

IN PROGRESS: US22 product identity + Excel export (#45/PR47) and US23 update
existing Excel in place (#46) on branch `feat/us23-update-excel` (stacked on
US22). US23 adds `analytics/excel_update.py` + `update_excel` command: opens an
existing "Productos vendidos" matrix, writes only the missing months (matching
rows by name with US22's fusion, appending new products), preserves historical
codes, writes a `… (actualizado).xlsx` copy, and warns on lock files / charts.
Also pending: US19 polished README (#20), deferred to last; the app is now
deployed (see [[mesa-heroku-deploy]] memory; branch `feat/us19-readme` has the
Heroku release config + demo seed fixture, not yet merged).

Identity + export (US22): POS clave is unreliable (reassigned/duplicated), so
products are identified by NAME. `catalog/identity.py` normalizes names (accents,
case, `*`, GR/ML/UND markers stripped) and a `ProductResolver` fuses obvious
variants (word order, typos, `*GR`, omitted "X Trago", and same-clave prefix like
"Negroni"->"Negroni Tanqueray") while keeping distinct ones separate (different
number/age/size; bottle-vs-glass by serving group). Each `(clave, raw_name)` is
recorded as a `catalog.ProductAlias` so identity is resolved once. `persist()`
uses the resolver for catalog-embedded importers (PDF); the Excel importer keeps
its SKU-based path. Excel export lives in `analytics/exports.py` (openpyxl):
`build_productos_vendidos_workbook` (units matrix) and `build_analysis_workbook`
(per-product/per-category + rankings, reusing `product_report`/`category_report`
in services). Command `export_excel --type matrix|report`; dashboard download
buttons hit `/export/...xlsx` views.

Analytics layer recap (all in `analytics/`): `services.py` holds the math
(`compute_kpis`, `revenue_by_day`, `top_products_by_revenue`, `revenue_by_category`,
`product_margins`, `monthly_pnl`), views stay thin and reuse `_resolve_range`
(defaults to last 30 days). Chart endpoints under `/api/...` return `{labels,data}`
JSON for Chart.js. Pages: `/` dashboard, `/margin/`, `/pnl/`. Theme lives in
`static/css/site.css` (warm steakhouse: charcoal + terracotta + gold, Inter).
Coverage gate: `pytest --cov-fail-under=70` enforced in `.github/workflows/ci.yml`.

i18n (US21): Django built-in i18n with `LocaleMiddleware`, `LANGUAGES=[en,es]`,
`LOCALE_PATHS=[locale/]`. Navbar has an EN/ES selector posting to `set_language`
(`/i18n/`), choice persisted via cookie. Source language EN; Spanish catalog in
`locale/es/LC_MESSAGES/django.po`. Chart.js labels are wrapped in `{% trans %}`
inside the templates (server-rendered). `.mo` files are gitignored and built by
`python manage.py compilemessages` (CI installs `gettext` and compiles before tests).

NEXT: finish/merge US21 bilingual EN/ES (#41, "should").
US19 Polished README (#20) is DEFERRED TO LAST by user decision (do it after the
other stories). US19 will need user inputs (live demo URL - not yet deployed,
business story, screenshots, board link). Confirm open work with `gh issue list`.

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
- Meat products report CANTIDAD in GRAMS (e.g. 2656), not units. Fine for revenue/margin;
  US15 top-products ranks by revenue (not units) for this reason.
- `analytics/api.py` and `analytics/serializers.py` are empty placeholders ("Filled in by
  US12") - chart endpoints ended up as plain JsonResponse views in `analytics/views.py`
  (catalog precedent), so DRF stays unused. Remove the placeholders or adopt DRF later.
- Local dev DB only: the `tomas` user password was reset to `preview123` during the UI
  refresh preview. Reset with `python manage.py changepassword tomas` if needed.

## Token efficiency (the user cares about this)
- Start a NEW session per user story to avoid dragging context.
- Prefer `pytest` + `curl` for verification; avoid screenshots (image tokens) and heavy
  skill loads unless visual confirmation is explicitly requested.
- Pull acceptance criteria from the GitHub issue instead of re-pasting long prompts.
