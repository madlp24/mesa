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
US31 multi-file upload (#63/PR69), US47 current product costs (#169/PR170),
US48 correct re-imported days (#171/PR172), US49 redesign (#174/PR175),
US50 menu engineering (#176/PR177), US51 days and holidays (#178/PR179),
US52 remaining pages redesigned (#180/PR181),
US53 menu engineering decisions (#183/PR184), US54 profitability alerts (#185/PR186),
US55 menu engineering by target food cost % (#187/PR188),
US56 suggested target per family (#189).
IN REVIEW: US33 event quotes with cost and margin (#78).
Epics catalog, ingestion, dashboard and analysis are COMPLETE.

US33 event quotes (#78): a `quotes` app turns the catalog into event proposals.
`MenuItem` is the client-facing layer over `catalog.Product` (the POS calls a dish
`CROQUETAS DE LOMO AHUMADO *4U`; a proposal must not), and its `product` link is
the only source of cost. `quotes/services.py` composes a menu from a per-guest
budget, reasoning in cost per guest = price / servings, with quantities rounded up
(two stations for 30 guests are paid whole). `quotes/pdf.py` renders the document
the client receives -- prices only, never cost or margin. Prices are quoted with
the impuesto al consumo inside, so the quote shows the contained tax and does not
add it again; the tip applies to the pre-tax base. A product carrying no cost is
treated as unknown, not free, so a quote using it reports no margin at all rather
than an inflated one. `python manage.py seed_menu --restaurant <id>` builds the
menu from the catalog; cuts sold by the gram become one-kilo items. Runtime dep
added: `reportlab` (was dev-only, for PDF test fixtures).

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

US56 suggested target per family (#189): `catalog/families.py` rules now carry
a suggested food cost (cuts 35, premium 40, starters 30, salads 28, sides 25,
add-ons 25, desserts 28, wine bottle 45, wine glass/sangria 35, cocktails 22,
spirits bottle 40, spirits glass 28, beers 35, soft drinks 25, other mains 32).
`target_of(category)` -> (target, "set"|"suggested"|"default"); a family takes
an owner-set target first, then a suggestion, then `Restaurant.target_cost_pct`.
Real 345 data (90d, weighted): kitchen ~30%, but drinks run above norms --
cocktails 30%, spirits by glass 39%, wine by glass 40%, add-ons 107% (lime
juice / chelada sold at a loss); the owner is to set his own drink targets.

US55 menu engineering by TARGET FOOD COST % (#187) -- supersedes the US53
pricing rule. The owner prices by food cost % (cost over price WITHOUT tax:
27.300 at 30% -> 91.000), not by the pesos a plate leaves. "Profitable" now
means `Dish.cost_pct <= target` (popularity still Kasavana-Smith 70%).
`Restaurant.target_cost_pct` (default 30, settings) with an optional
`Category.target_cost_pct` override per POS group on the families page (a
family takes any override among its groups -- wines run 40-50%, set theirs).
`price_moves` covers EVERY dish over target at today's menu price: needed =
ceil(cost / target * 1.08, step), capped per change; figures rounded to the
cent before the step (1.08 division noise). `contribution_threshold` is only
kept for reference. Simulator and scatter speak cost %.

US54 profitability alerts (#185): new `alerts` app. `AlertSettings` (one per
restaurant, created on first read): cadence week (7 days) / month (30 days) up
to the NEWEST report, baseline previous (4 weeks / 30 days) or last year (364
days back, weekdays aligned), thresholds cost_rise 5%, margin_drop 3 pts,
abrupt_change 15%, min_weekly_sales 300.000. `alerts/engine.py::build_report`
(`as_of=` reads a past period, never "behind"): products that lost
profitability (cost per portion up / price down / margin points down) with
`monthly_loss`; abrupt changes = a day whose POS cost or price breaks from the
median of its previous 10 sale days, and a supplier purchase vs the previous
purchase (`catalog.SupplyPrice`, the price HISTORY: `sync_supplies` appends a
row per new purchase instead of only overwriting `Supply.unit_cost`); causes =
recipe supplies whose price moved. `sync_all_supplies` command for a daily
scheduler. Pages `/alerts/` (+ `?as_of=`), `/alerts/settings/`, Excel and PDF
downloads. Backtest on real data: the week to 2026-07-05 flags the picanha cost
jump (+14%, POS cost 23.309 -> 27.587 on Jul 3). NEXT: delivery (recipients,
email, WhatsApp via the bot, scheduled send).

US53 menu engineering: families, board, movement, decisions (#183). Dishes are
compared within a MENU FAMILY, not a raw POS group: `catalog/families.py`
suggests one per category from its name (and hides voids/corkage);
`Category.menu_family` / `menu_hidden` (blank/null = use the suggestion) hold
what the owner set on `/margin/menu/families/`. The page is a 2x2 board (tiles
sized by takings), the scatter is a secondary view. `with_movement` attaches
the previous window's dish (cost change, portions change, quadrant it came
from; `Group.cost_drift` = what cost rises take at today's sales).
`price_moves`: for each plowhorse the MENU price (consumption tax 8% included,
per 100 g for gram cuts; the POS stores it without tax) that makes a portion
leave the family average, capped at `Restaurant.price_rise_cap` (default 8%)
and rounded to `Restaurant.menu_price_step` (default 1000), both in settings.
`weakest_dogs` only lists dogs under 1.5% of the family's margin. Client-side
price simulator. Agreed roadmap after this: weekly profitability alert
(configurable comparison + recipients, daily AutoFacturas sync with supplier
price history), then protein shortfalls (monthly count lives in Soft;
butchering "producciones"). Mesa is NOT becoming a POS.

US50 menu engineering (#176): `analytics/menu_engineering.py`, tab in Margins
(`/margin/menu/`, default 90 days -- new `90d` preset). Kasavana-Smith WITHIN
each category: popular = share of the group's portions >= 70% of an even share;
profitable = contribution per portion >= the group's portion-weighted average.
Cuts sold by the gram count in 280 g portions (`catalog/portions.py`, same
number the quotes use) -- otherwise grams outrank pieces. Uncosted dishes are
listed apart, never placed.

US51 days and holidays (#178): `analytics/days.py`, tab in Sales (`/days/`,
whole history by default). Colombian holidays (Emiliani Mondays) from the
`holidays` package (runtime dep). Reads `DailySummary` when the restaurant has
covers, else POS sales per day; weekday averages exclude holidays; a holiday
after the newest report is "no report yet", never "closed". Upcoming holidays
expect what same-weekday holidays sold in the last 365 days.

US52 (#180): remaining pages on the new design; `.narrow` left column replaces
centred cards (auth pages stay centred); workbook form defaults to the month of
the newest report.

US49 redesign: navigation, dashboard and design system (#174/PR175). The UI
was a generic cream/terracotta card kit with every page behind ONE dropdown.
Now: a fixed side rail (`templates/base.html`, Bootstrap `offcanvas-lg` so it
becomes an off-canvas menu on phones) listing six sections from
`pages/navigation.py::SECTIONS`; a context processor marks the active section
and renders its sibling pages as tabs (margins+alerts, comparisons+P&L,
products+supplies+duplicates, quotes+event menu). Signed-in `/` redirects to
the dashboard (the card hub `pages/home.html` is gone). Periods:
`analytics/periods.py::window_for` -- presets `?period=7d|30d|month|
last_month|year` or `?start=&end=`; with neither, the 30 days ending on the
NEWEST DAY WITH SALES (ending on today showed $0 whenever reports were behind),
and `Window.days_behind` drives a "reports missing" notice
(`templates/includes/{period,freshness}.html`). `analytics/overview.py` feeds
the dashboard: sales vs the previous window of equal length, margin in points,
people and per-bill from `DailySummary` (the old "average ticket" divided by
synthetic per-product sales and "items sold" added grams to bottles -- both
dropped), a per-day series that keeps closed days as gaps, to-review list,
rankings. Money goes through `pages/templatetags/mesa.py` (`cop`, `cop_short`,
`num`, `pct`, `change`, `signed`, `trend`); Spanish numbers follow Colombia via
`FORMAT_MODULE_PATH = ["config.formats"]` ("$276.436.986"). Design tokens in
`static/css/site.css` (Archivo at two widths, charcoal/bone, one ember accent;
herb/amber/loss reserved for margin health). Trap: a `{{ _('...') }}` template
literal doubles its `%` before lookup, so JS placeholders use `{n}`, not
`%(n)s`. The quotes page builds the event menu from a button
(`quotes:menu_build`, wraps `seed_menu`).

US48 correct a re-imported day instead of skipping it (#171/PR172): `persist()`
used to skip any existing `external_id`, so a daily report printed before close
and re-imported in full stayed partial forever. A stored sale with different
figures (compared to the cent) is now rewritten in place, keeping its ORIGINAL
batch -- option B, agreed with the owner: a correction is NOT undone by undoing
the correcting import. Guard against an older partial copy: corrections apply
per day only when the file's total over that day's stored sales is >= what is
stored; otherwise counted as `skipped_older`. `ImportBatch.sales_corrected` /
`skipped_older` are shown on the upload page, undo message and CLI.

US47 product cost and price follow the newest sale (#169/PR170): `cost_price`
/`sale_price` used to be written once at creation (223 of 359 costs and 78
prices stale on the real catalog; NEW YORK STEAK showed 61.1% vs a real 71.1%).
`catalog/pricing.py::refresh_product_prices` sets them from each product's
NEWEST SALE DAY (by date, not import order -- folders arrive out of order),
quantity-weighted, ignoring zeros (courtesies, uncosted lines). Called by
`persist()`, `undo_import`, merge/re-point/split. `cost_price` now BELONGS TO
THE POS: the supply sync and recipe editor no longer write it; a complete
recipe wins live via `Product.effective_cost`. `/margin/` reads
`effective_cost`, and an uncosted product shows "No cost" / no margin (was
100%), sorted last. Backfill: `refresh_product_costs --restaurant <slug>
[--dry-run]` (run on the local DB 2026-11-24: 232 products changed).
Remaining difference: `/margin/alerts/` still judges on the POS cost stored on
each sale line, so a product with a recipe can differ between the two pages.

US46 quote margin from the live supply cost, with a minimum (#164): a
`QuoteLine.unit_cost` is a snapshot taken when the line is added, so a quote
already sent does not change under the client's feet -- which also means a quote
priced before the costs landed keeps reporting the old margin. `Quote.current_cost`
/ `current_margin_pct` / `cost_drift` read through to the menu instead, so the
drift is visible, and the pages judge on those; the stored costs are only
rewritten by an explicit "Update the quote's costs" button. `Product.effective_cost`
is the live answer (`recipe_cost` when the recipe is complete, else `cost_price`)
and `MenuItem.unit_cost` reads it, so a supply price rise reaches the quote
without waiting for a sync. (Since US47 nothing writes the recipe cost onto
`cost_price`; see below.) The target margin
stopped being `TARGET_MARGIN = 60` in views.py: it is
`Restaurant.minimum_quote_margin`, editable in settings, and quotes under it are
flagged on the list and the detail. A quote nobody can cost is reported as
unknown, never as "below".

US45 cost products from AutoFacturas supplies, with recipes (#162): AutoFacturas
(the owner's invoice-reading project, `~/Documents/Integracion Siesa`) publishes
`GET /conector/costos` -- Bearer per company -- with what one unit of consumption
of each insumo costs (unidad/ml/g), taxes the restaurant cannot discount already
inside. `catalog/supplies.py` splits the job in three so each is testable on its
own: `fetch_costs` (stdlib urllib, no new dependency), `sync_supplies` (upsert by
`clave`, the only field that survives a rename), `recost_products`.
`catalog.Supply` mirrors an insumo; `catalog.RecipeLine` says how much of one a
single unit of a product consumes, in the supply's own unit -- one line is the
simple link (a bottle poured by the glass), several make a cocktail, which is the
only way a negroni can carry a cost. Rules that matter: a zero cost is NO cost
(the connector sends null for what it could not cost); a recipe with one uncosted
supply reports no cost AT ALL and leaves the POS cost standing, rather than a
short sum that would read as real; supplies the payload stops mentioning are kept,
because AutoFacturas drops an insumo it cannot cost and deleting it would take its
recipes with it. `MenuItem.unit_cost` follows for free through `product_units`.
The Bearer token is per tenant (`Restaurant.autofacturas_token`), write-only in
the UI and never rendered back. Command `sync_supply_costs --restaurant <slug>
[--days 90] [--file <saved.json>] [--dry-run]`; page `/products/supplies/`, recipe
editor on the product detail page.

US44 drop the closed days from "Datos totales" (#154): the restaurant does not
open on ordinary Mondays, only on holiday ones, so `prune_closed_days --file
<xlsx> [--weekday lunes] [--through YYYY-MM-DD]` deletes the empty Monday rows
and keeps every Monday that had movement. Two traps it has to handle: a closure
was sometimes typed as `0` rather than left blank (a literal zero counts as no
movement), and the sheet runs a calendar skeleton ahead of itself -- empty rows
with the weekday already typed, waiting to be filled -- so only days up to
`--through` (today by default) are considered; pruning a future holiday Monday
would just send it to the bottom of the sheet when its report arrives.
Deleting rows mid-sheet is not free: the per-row formulas are self-row
references and openpyxl does not translate them when rows shift, so
`_repoint_row_formulas` rewrites every surviving row's formulas to its own row,
preserving each row's own formula columns (only some rows carry the madurado
block). Run on the real workbook: 17 closed Mondays removed, 38 holiday Mondays
kept, 13 future skeleton rows untouched, 2879 formulas re-pointed -- which also
fixed two rows that already pointed at a neighbour (row 136's madurado formula
and the appended 2026-01-26 row).

US43 fill "Estados de Resultados" from the accountant's statements (#152): the
owner's P&L sheet stops where his accountant's statements start. `analytics/
estado_resultados.py` reads the UNO 8.5 "ESTADO DE RESULTADOS" PDF -- up to four
monthly columns per file, PUC accounts at level 08 -- assigning each amount to a
month by its **x position** (a row prints only the months it moved in, so order
on the line means nothing) and undoubling the bold subtotal lines (bold is drawn
by overprinting, so every glyph comes out twice: "11,,000000"). The sheet is
deliberately not a mirror of the statement: `ROW_ACCOUNTS` maps every leaf
account onto exactly one row (APORTES SOCIALES gathers the four aportes plus
gastos medicos; OTROS gathers what is left of DIVERSOS), and `reconcile()`
rebuilds the statement's own printed totals from the mapped rows and refuses to
write when they disagree. Row 12 takes the statement's whole COSTOS total (which
carries bajas, desperdicios y traspasos), matching what the owner typed by hand
from ago-2024 on -- so "% Costo/Venta" is noisier than rows 10+11 alone.
`update_estados_resultados --file <xlsx> --pdf <statement> [--pdf ...]` appends a
column per month, replicating the sheet's own formula rows; rows the accountant
books nothing on stay blank, not zero. Validated on ene-ago 2026: 123 accounts,
0 descuadres.

US31 multi-file upload (#63): `/upload/` accepts several files at once
(`sales/forms.py MultipleFileField`); `upload_report` imports each (one ImportBatch per
file), a per-file error is reported without aborting the batch.

DEPLOYED 2026-11-26 (Heroku release v55): everything through US53 is LIVE.
See [[mesa-heroku-deploy]]. Writing to production DATA needs the owner's
explicit ask (the auto-mode classifier blocks it otherwise).

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
