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
  before committing. Do not add importer deps (openpyxl/pdfplumber/pandas) until their
  stories.

## Status (update as work lands)
- US1 Scaffold (#1) - DONE
- US3 Sign up / log in (#2) - DONE (merged, PR #22)
- US4 Log out (#3) - DONE, PR #23 open (awaiting merge)
- NEXT: US5 Manage product categories (#4) - Sprint 1, "must".
  Note: the `Category` model already exists from the scaffold; US5 is mainly a model
  test for ordering plus verifying admin CRUD. Confirm against `gh issue view 4`.

## Known follow-ups (not blocking)
- #24 Navbar lacks a Bootstrap toggler -> logout/login hidden below 992px (mobile).

## Token efficiency (the user cares about this)
- Start a NEW session per user story to avoid dragging context.
- Prefer `pytest` + `curl` for verification; avoid screenshots (image tokens) and heavy
  skill loads unless visual confirmation is explicitly requested.
- Pull acceptance criteria from the GitHub issue instead of re-pasting long prompts.
