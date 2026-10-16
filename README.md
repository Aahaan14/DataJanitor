# DataJanitor — Automatic Dataset Repair Assistant

DataJanitor is an automatic dataset quality analysis and repair assistant.
Upload a CSV dataset, the system identifies data-quality issues, recommends
corrections, lets you review and approve or reject each proposed fix, and
download the cleaned dataset.

> **Status:** Phase 1 — Project foundation ✅

---

## Quick Start (Backend)

### Prerequisites

- Python 3.11 or later
- `pip` (bundled with Python)

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd DataJanitor
```

### 2. Create a virtual environment

```bash
cd backend
python -m venv venv

# Activate — Windows (PowerShell)
.\venv\Scripts\Activate.ps1

# Activate — macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

```bash
copy .env.example .env     # Windows
# cp .env.example .env     # macOS / Linux
```

Edit `.env` as needed. The defaults work for local development.

### 5. Run the development server

```bash
uvicorn app.main:app --reload
```

The API is available at **http://127.0.0.1:8000**.

- Health check: `GET http://127.0.0.1:8000/health`
- Interactive docs: `http://127.0.0.1:8000/docs`

### 6. Run the test suite

```bash
pytest -v
```

---

## Project Structure

```
DataJanitor/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI entry point
│   │   ├── config.py            # pydantic-settings configuration
│   │   ├── api/
│   │   │   └── routes/
│   │   │       └── health.py    # GET /health
│   │   ├── core/                # Middleware, security (future)
│   │   ├── schemas/             # Pydantic request/response models
│   │   │   └── health.py
│   │   ├── models/              # SQLAlchemy ORM models (Phase 5)
│   │   ├── services/            # Business logic (Phase 2+)
│   │   ├── database/            # Engine, session (Phase 5)
│   │   └── utils/               # Helpers, constants
│   ├── tests/
│   │   ├── conftest.py          # Shared fixtures
│   │   └── test_health.py       # Health endpoint tests
│   ├── sample_data/             # Example CSVs (Phase 10)
│   ├── requirements.txt
│   ├── pyproject.toml           # Pytest config
│   ├── .env.example
│   └── .env                     # Local only, git-ignored
├── frontend/                    # React + TypeScript (Phase 8)
├── .gitignore
└── README.md
```

---

## Development Phases

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Project foundation | ✅ Done |
| 2 | CSV upload & preview | ⬜ Pending |
| 3 | Data-quality detection engine | ⬜ Pending |
| 4 | Validation & repair recommendations | ⬜ Pending |
| 5 | Database & audit history | ⬜ Pending |
| 6 | Cleaned dataset generation | ⬜ Pending |
| 7 | Email reporting | ⬜ Pending |
| 8 | React frontend | ⬜ Pending |
| 9 | Integration, security & testing | ⬜ Pending |
| 10 | Documentation & demonstration | ⬜ Pending |

---

## License

This project is a student mini project for educational purposes.
