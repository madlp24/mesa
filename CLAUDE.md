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
- ALWAYS keep the GitHub Project board up to date (board **"Mesa Devolopment"**,
  https://github.com/users/madlp24/projects/6). Every new story gets a GitHub issue
  that is added to the board; when work lands (PR merged / issue closed) its card must
  be in **Done**; work in flight goes to **In Progress**. Non-story work (chores, docs,
  refactors) that ships as a PR without an issue is added to the board as the PR itself
  and set to Done. The board must reflect everything in this Status section — nothing
  shipped should be missing from it. (Needs the `project` gh scope:
  `gh auth refresh -s project`; Status field id `PVTSSF_lAHOBy5ZcM4BYiM8zhTnauQ`,
  Done option `98236657`; add items with `gh project item-add 6 --owner madlp24 --url <url>`
  then `gh project item-edit --project-id PVT_kwHOBy5ZcM4BYiM8 --id <item> --field-id <status> --single-select-option-id <opt>`.)
- Python 3.11+ syntax, type hints where natural, PEP 8, no emojis. Run `ruff check .`
  before committing. Importer deps are added per-story as needed (already present:
  `openpyxl`, `pdfplumber` runtime; `reportlab` dev, only for PDF test fixtures).
- Lint config lives in `ruff.toml` (added #80/PR81). Mesa runs ruff's DEFAULT rule set
  (416 rules as of 0.16) and the file's job is to record the opt-outs: `RUF012` is off
  because it is a Django false positive (`Meta.ordering`/`constraints` and migration
  `dependencies`/`operations` are read off the class by Django itself), and `FURB157`
  is off because every monetary `Decimal` is built from a string on purpose. `F403` is
  re-selected for the settings star-imports; `target-version = "py312"`. Pin is
  `ruff>=0.16`, no ceiling -- if a ruff upgrade surfaces new findings, fix them or add
  an ignore WITH a written reason to `ruff.toml`; do not pin the version to hide them.

## Status (update as work lands)
DONE + merged: US1 Scaffold (#1), US3 auth (#2/PR22), US4 logout (#3/PR23),
US5 categories (#4/PR25), US6 products (#5/PR26), US7 product detail (#6/PR27),
US8 Excel import (#7/PR28), US9 PDF import (#8/PR29), US10 skip-duplicates (#9/PR30),
US11 pluggable arch (#10/PR31), US12 dashboard KPIs (#11/PR32),
US13 date-range default (#12/PR33), US14 revenue line chart (#13/PR34),
US15 top-products bar (#14/PR35), US16 revenue-by-category doughnut (#15/PR36),
US17 margin analysis page (#16/PR37), US18 monthly P&L (#17/PR38),
US20 test coverage + CI (#18/PR40), navbar toggler fix (#24/PR39),
UI visual refresh (PR42), US2 onboarding (#19/PR43), US21 bilingual EN/ES (#41/PR44),
US22 product identity + Excel export (#45/PR47), US23 update existing Excel (#46/PR49),
US24 multi-tenant foundation (#50/PR52), US25 self-service web upload (#51/PR53),
US26 first-run experience (#57/PR58), US28 import history + undo (#59/PR60),
US29 manage product identity in the UI (#61/PR62),
US30 update master 'Productos vendidos' sheet (#64/PR65),
US32 fill 'Datos totales' N/O/S/T from PDF footer (#66/PR68),
US31 multi-file upload (#63/PR69).
Epics catalog, ingestion, dashboard and analysis are COMPLETE.

PRODUCT PIVOT (agreed with user): Mesa is now a generic, **multi-tenant SaaS** for any
restaurant using the Soft Restaurant POS (not just Tres Cuatro Cinco). Each user gets
their own restaurant and sees only their data; report upload happens on the web at
`/upload/` (`sales/forms.py` + `sales/views.py upload_report` -> importer/persist into
`request.restaurant`; navbar "Upload"; Django messages in base.html).

DEPLOYED 2026-06-26 (Heroku release v7): multi-tenant + web upload are LIVE on the demo.
Translations compile at build via `bin/post_compile` (release-dyno fs is ephemeral).
US26 first-run experience (#57): signup asks for the restaurant name
(`ACCOUNT_SIGNUP_FORM_CLASS=tenants.forms.RestaurantSignupForm` renames the
signal-created restaurant); empty dashboard shows an "Upload your first report" CTA
(view passes `has_data`); `/settings/` page (`tenants.views.settings`) renames the
restaurant, linked from the navbar restaurant name.
US28 import history + undo (#59): `sales.ImportBatch` records each import (filename,
source web/cli, counts); `Sale.import_batch` FK tags created sales. `sales/services.py`
`run_import()` (used by the upload view and `import_sales`) creates the batch; the
upload page lists recent imports with an Undo button -> `undo_import_view` deletes that
batch's sales (tenant-scoped).

US29 manage product identity in the UI (#61): a `/products/` page (catalog
`product_list`, navbar "Products") lists products with alias count / units / revenue;
select 2+ and **merge** into a canonical (moves sale items + aliases, deletes the rest).
The product detail page lists POS aliases; each can be **re-pointed** to another product
or **split** into a new one, and the historical sales for that clave follow it. Logic is
in `catalog/services.py` (`merge_products`/`repoint_alias`/`split_alias`), tenant-scoped,
raising `IdentityError` on cross-tenant refs.

US30 + US32 update the owner's real master workbook ("Análisis unificado ....xlsx")
via LOCAL commands (not on the web; the master file lives on the owner's Mac). Code in
`analytics/unified_excel.py` (two-row-header aware; writes a COPY, never the original):
- US30 (#64) `update_unified --file <xlsx> --restaurant <slug> --year --month`: fills the
  "Productos vendidos" units matrix column for that month, matching rows by NAME (US22
  fusion), appending unmatched products, reporting appended names to review.
- US32 (#66) `update_datos_totales --file <xlsx> --pdf-dir <folder>`: fills "Datos totales"
  N/O/S/T (Venta/Costo Bar y Cocina) from each daily PDF's footer, parsed by
  `sales/importers/pdf_daily.py::parse_daily_totals` (BEBIDAS/ALIMENTOS block). Matches by
  date and fills in place; missing dates are appended with per-row formulas replicated.
  See [[productos-vendidos-update-process]] for the full monthly workflow.

US31 multi-file upload (#63): `/upload/` accepts several files at once
(`sales/forms.py MultipleFileField`); `upload_report` imports each (one ImportBatch per
file), a per-file error is reported without aborting the batch.

DEPLOYED 2026-07-08 (Heroku release v10): US29 + US30 + US32 + US31 are LIVE (US30/US32
are local commands, no web surface). See [[mesa-heroku-deploy]].

NEXT: US19 polished README (#20), DEFERRED TO LAST by user decision; needs user inputs
(business story, screenshots, board link — live demo URL is now known). The old
`feat/us19-readme` branch has an early Heroku config + a demo seed fixture that predates
the restaurant FK (would need a restaurant before any reload); the real deploy config is
already on `main`. Optional backlog: madurado columns (Z/AA/AB/AC) in "Datos totales"
(owner said not needed for now). Confirm open work with `gh issue list`.

Multi-tenancy (US24): shared-DB, row-level scoping. New `tenants` app: `Restaurant` +
`Membership` (one restaurant per user). A `post_save` on User auto-creates a
restaurant+membership (`tenants/signals.py`); `CurrentRestaurantMiddleware` sets
`request.restaurant`. `Category`/`Product`/`ProductAlias`/`Sale` got a `restaurant` FK
with per-restaurant uniqueness. Data migration assigned existing rows to a "Demo"
restaurant. ALL analytics services/exports/excel_update, the importer
`persist()`/`ProductResolver`, and catalog views scope by restaurant (services take
`restaurant` as the first positional arg). Commands take `--restaurant <slug>` via
`tenants.utils.resolve_restaurant`. Isolation covered in `tenants/tests.py`.

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

(i18n note: `.po` entries must not be left `#, fuzzy` — Django treats fuzzy as
untranslated and shows English. After `makemessages`, translate AND clear the fuzzy flag;
check with `msgattrib --only-fuzzy`.)

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
  Real sample PDFs live on the user's Desktop under `VENTA COSTO 2025/<MONTH>/` (daily
  `Venta-Costo DD Mes 2025.pdf` + a monthly `... mes ....pdf` summary), not in the repo;
  the PDF tests use synthetic reportlab fixtures that mimic the real layout. Validated on
  MARZO 2025 (2026-07): 27 daily PDFs parse with 0 skipped rows; the footer has a real
  `ALIMENTOS :` space-before-colon variant handled by `parse_daily_totals`.

## Known follow-ups (not blocking)
- Meat products report CANTIDAD in GRAMS (e.g. 2656), not units. Fine for revenue/margin;
  US15 top-products ranks by revenue (not units) for this reason.
- Chart endpoints are plain JsonResponse views in `analytics/views.py` (not DRF). The
  unused DRF dependency and its empty `analytics/api.py`/`serializers.py` placeholders
  were removed (chore, 2026-07-08); adopt DRF later only if a real API is needed.
- Local dev DB only: the `tomas` user password was reset to `preview123` during the UI
  refresh preview. Reset with `python manage.py changepassword tomas` if needed.

## Token efficiency (the user cares about this)
- Start a NEW session per user story to avoid dragging context.
- Prefer `pytest` + `curl` for verification; avoid screenshots (image tokens) and heavy
  skill loads unless visual confirmation is explicitly requested.
- Pull acceptance criteria from the GitHub issue instead of re-pasting long prompts.
