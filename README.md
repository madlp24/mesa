# Mesa

Restaurant business intelligence dashboard built with Django and Chart.js, powered by
real POS data from Tres Cuatro Cinco steakhouse in Bogota, Colombia.

## Local Setup

```powershell
git clone https://github.com/madlp24/mesa.git
cd mesa
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
# edit .env and set a SECRET_KEY
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Project status: scaffold phase. See the [Project Index](../../issues/21) for user
stories and sprint plan.
