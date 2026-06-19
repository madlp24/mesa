# Mesa

Restaurant business intelligence dashboard built with Django and Chart.js, powered by
real POS data from Tres Cuatro Cinco steakhouse in Bogota, Colombia.

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

The dashboard needs sales data to render charts. Import a POS file with:

```bash
python manage.py import_sales --file <path-to-excel-or-pdf>
```

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
