# Mesa

Multi-tenant business intelligence for restaurants that use the **Soft Restaurant**
POS. Upload your "Productos Vendidos" reports and get instant dashboards, margin and
P&L analysis, and a clean Excel of your own data to work with. Built with Django and
Chart.js. Each restaurant signs up and sees only its own data.

## Local Setup

Get the app running locally in under 5 minutes.

### Prerequisites

- **Python 3.12** (the project pins `python-3.12.7`; 3.11+ works for development)
- **git**

Check your version with `python3 --version`.

### macOS / Linux

```bash
git clone https://github.com/madlp24/mesa.git
cd mesa

# 1. Create and activate a virtualenv
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies (dev set includes tests + linters)
pip install -r requirements-dev.txt

# 3. Create your local .env from the template
cp .env.example .env

# 4. Generate a SECRET_KEY and paste it into .env
python -c "import secrets; print(secrets.token_urlsafe(50))"

# 5. Set up the database (creates a local db.sqlite3)
python manage.py migrate

# 6. Create an admin user to log in with
python manage.py createsuperuser

# 7. Run the dev server
python manage.py runserver
```

### Windows (PowerShell)

```powershell
git clone https://github.com/madlp24/mesa.git
cd mesa

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt

Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(50))"
# paste the printed value as SECRET_KEY in .env

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

The app is now at <http://127.0.0.1:8000/>. Log in with the superuser you created.
The Django admin lives at <http://127.0.0.1:8000/admin/>.

### Environment variables

`.env` is gitignored and read via `python-decouple`. Copy `.env.example` and adjust:

| Variable | Default | Notes |
| --- | --- | --- |
| `SECRET_KEY` | — | Required. Generate with the command above. |
| `DEBUG` | `True` | Keep `True` for local development. |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated. |
| `DATABASE_URL` | empty | Leave empty to use the local SQLite database. |
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` | Dev settings use SQLite. |

### Loading sample data

The dashboard needs sales data to render charts. The primary way is the **Upload**
page in the navbar: pick your Soft Restaurant "Productos Vendidos" export (`.pdf` or
`.xlsx`) and it is imported into your restaurant, with a summary of what was added.

The same import is available from the command line:

```bash
python manage.py import_sales --file <path-to-excel-or-pdf> --restaurant <slug>
```

Mesa is **multi-tenant**: every user belongs to a restaurant (created automatically on
signup) and only ever sees that restaurant's data. `--restaurant` is optional when only
one restaurant exists. The export/update commands below take the same flag.

Products are identified by **name** (not the unreliable POS code): the importer
resolves each `(code, name)` to one canonical product and records the decision as
a `ProductAlias`, fusing obvious variants while keeping genuinely different items
(different age/size/serving) apart.

### Exporting to Excel

Generate `.xlsx` files from the real data (also available as download buttons on
the dashboard):

```bash
python manage.py export_excel --type matrix --output productos_vendidos.xlsx
python manage.py export_excel --type report --output analisis.xlsx --start 2026-01-01 --end 2026-12-31
```

`matrix` is the Productos-Vendidos units-per-month matrix; `report` is the analysis
report (per product and per category, plus top-N rankings).

### Updating an existing workbook in place

To write the new months into your own existing "Productos vendidos" workbook
(matching rows by name, appending genuinely new products), without touching the
original:

```bash
python manage.py update_excel --file "Análisis unificado.xlsx"
```

It writes a copy `… (actualizado).xlsx`, never the original, preserves historical
codes, and warns if the workbook looks open in Excel or contains charts/macros
(which openpyxl cannot preserve).

### Running tests and linting

```bash
python -m pytest -q        # test suite (coverage gate: 70%)
ruff check .               # lint
```

## Languages (English / Spanish)

The UI is fully bilingual. Use the **language selector in the navbar** to switch
between English and Spanish; the choice is stored in a cookie and persists across
requests. English is the source language; Spanish lives in
`locale/es/LC_MESSAGES/django.po`.

Compiled catalogs (`.mo`) are not committed — build them once after cloning:

```bash
python manage.py compilemessages
```

> This needs the GNU `gettext` tools. On macOS: `brew install gettext`.
> On Debian/Ubuntu: `sudo apt-get install gettext`.

### Adding or updating translations

1. Mark new strings for translation in templates (`{% trans %}` / `{% blocktrans %}`)
   or in Python (`gettext` / `gettext_lazy`).
2. Regenerate the catalog and translate the new `msgstr` entries:

   ```bash
   python manage.py makemessages -l es --ignore=.venv --ignore=staticfiles
   # edit locale/es/LC_MESSAGES/django.po
   python manage.py compilemessages
   ```

## Project status

Catalog, ingestion, dashboard, and analysis epics are complete. See the
[Project Index](../../issues/21) for user stories and the sprint plan.
