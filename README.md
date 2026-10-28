# 🧹 DataJanitor — Automatic Dataset Repair Assistant

**Find data-quality issues. Review suggested fixes. Clean your datasets with confidence.**

DataJanitor is a web-based dataset quality analysis and repair assistant that helps users identify data-quality problems in CSV files, understand suggested corrections, and generate cleaned datasets through a controlled review process.

Instead of modifying data silently, DataJanitor provides visibility into detected issues and proposed changes, allowing users to review recommendations before applying them.

## ✨ Features

### Dataset Management
- Upload CSV datasets for analysis.
- Preview dataset contents and inspect columns.
- View row counts, column counts, inferred data types, and statistical summaries.
- Analyze the currently selected dataset independently.

### Data Quality Analysis
- Detect missing values.
- Identify duplicate records.
- Detect inconsistent formats and whitespace.
- Identify invalid or unexpected values.
- Flag suspicious statistical outliers.
- Generate dataset profiling statistics.

### Intelligent Repair Suggestions
- Recommend appropriate corrections for detected issues.
- Display suggested values for missing or invalid entries when appropriate.
- Explain proposed changes where supported.
- Review suggested corrections before applying them.
- Approve or reject proposed repairs.
- Support bulk approval of suggested changes where available.

### Cleaning and Export
- Apply approved changes to a working copy of the dataset.
- Preserve the original uploaded data.
- Generate and download cleaned CSV files.
- Review the resulting dataset after repairs.

### Dashboard and History
- View quality metrics for the selected dataset.
- Inspect issue summaries and repair statistics.
- Review available dataset and scan information.

### Reliability and Testing
- REST API powered by FastAPI.
- Persistent data storage using SQLite and SQLAlchemy.
- Automated backend and frontend tests.
- Input validation and error handling.

> Feature availability depends on the current implementation. Consult the running application and API documentation for the exact functionality supported by your version.

## 🛠️ Technology Stack

| Component | Technologies |
|---|---|
| Frontend | React, TypeScript, Vite |
| Styling | Tailwind CSS |
| Backend | Python, FastAPI, Uvicorn |
| Data processing | Pandas |
| Validation | Pydantic; Pandera where integrated |
| Database | SQLite, SQLAlchemy |
| Testing | Pytest, HTTPX, Vitest |
| Version control | Git and GitHub |

## 📁 Project Structure

The project is organized into separate frontend and backend applications.

```text
DataJanitor/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   ├── core/
│   │   ├── schemas/
│   │   ├── models/
│   │   ├── services/
│   │   │   ├── profiling_service.py
│   │   │   └── detection_service.py
│   │   ├── database/
│   │   └── utils/
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   ├── tests/
│   ├── package.json
│   ├── vite.config.ts
│   └── .env.example
├── .gitignore
└── README.md
```

Some folders and files may vary by version. Check your local repository for the complete structure.

## 💻 Prerequisites

Install the following before running the project:

- **Python 3.11 or later** — use a version compatible with your installed dependencies.
- **Node.js and npm** — Node.js 24 LTS or another compatible version is recommended.
- **Git** — for version control.
- **VS Code** or another code editor.

SQLite is used for local database storage, so a separate database server is not normally required.

## 🚀 Installation and Setup

These instructions are for Windows using PowerShell.

### 1. Clone the repository

If you have not cloned the repository yet:

```powershell
git clone https://github.com/Aahaan14/DataJanitor.git
cd DataJanitor
```

If the project is already on your computer, open PowerShell in the existing project directory instead.

### 2. Set up the backend

Open the first terminal and navigate to the backend:

```powershell
cd backend
```

Create a virtual environment if one does not already exist:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution, use the following command for the current terminal session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then activate the environment again.

Install the Python dependencies:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Configure environment variables

Check whether the backend has an `.env.example` file:

```powershell
Get-ChildItem -Force
```

If it exists, create a local `.env` file:

```powershell
Copy-Item .env.example .env
```

Open `.env` and configure the variables required by the application.

Keep credentials, SMTP passwords, and other secrets in your local environment. Never commit your `.env` file to GitHub.

If the application uses default local SQLite settings and does not require additional configuration, follow the configuration already provided by the project.

### 4. Start the backend

From the `backend` directory, run:

```powershell
python -m uvicorn app.main:app --reload
```

The backend should be available at:

- **API:** http://127.0.0.1:8000
- **Interactive API documentation:** http://127.0.0.1:8000/docs
- **Alternative API documentation:** http://127.0.0.1:8000/redoc

Keep this terminal running.

### 5. Set up the frontend

Open a second terminal in VS Code or PowerShell.

Navigate to the frontend directory from the project root:

```powershell
cd "$HOME\Documents\OneDrive\Desktop\Projects\DataJanitor\frontend"
```

If your project is stored elsewhere, replace the path with your actual location.

Install the frontend dependencies:

```powershell
npm ci
```

If `npm ci` fails because the project does not have a valid lockfile, inspect the error before trying `npm install`.

### 6. Configure the frontend

If the frontend contains an `.env.example` file, create a local `.env` file:

```powershell
Copy-Item .env.example .env
```

Set the backend API URL according to the variable name expected by the frontend.

For Vite applications, client-side environment variables generally use the `VITE_` prefix. Never put private API keys or server-side secrets in frontend environment variables.

### 7. Start the frontend

Run:

```powershell
npm run dev
```

Vite will print a local development URL, typically:

**http://localhost:5173**

Open the displayed URL in your browser. Keep both terminal windows running while using DataJanitor.

## ▶️ Quick Start — Existing Installation

If you have already installed the dependencies, you can start DataJanitor using two terminals.

**Terminal 1 — Backend**

```powershell
cd "$HOME\Documents\OneDrive\Desktop\Projects\DataJanitor\backend"
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
```

**Terminal 2 — Frontend**

```powershell
cd "$HOME\Documents\OneDrive\Desktop\Projects\DataJanitor\frontend"
npm run dev
```

Open http://localhost:5173.

## 🧪 Running Tests

Run the backend tests from the `backend` directory with the virtual environment activated:

```powershell
python -m pytest
```

For more detailed test output:

```powershell
python -m pytest -v
```

Run frontend tests from the `frontend` directory:

```powershell
npm test
```

If the `test` script is not defined, inspect the available scripts:

```powershell
npm run
```

Run the production frontend build:

```powershell
npm run build
```

If configured, run the frontend test suite and production build before committing significant changes.

## 🔌 API Documentation

DataJanitor exposes a REST API through FastAPI.

After starting the backend, visit:

- Swagger UI: http://127.0.0.1:8000/docs
- ReDoc: http://127.0.0.1:8000/redoc

These interfaces show the routes, request parameters, response schemas, and available operations implemented in the running backend.

Use the API documentation as the source of truth for endpoint names and request formats.

## 🔄 Typical Workflow

1. Start the backend and frontend.
2. Open the DataJanitor dashboard.
3. Upload a CSV dataset.
4. Review the dataset preview and profiling statistics.
5. Analyze the dataset for quality issues.
6. Inspect the detected issues and proposed corrections.
7. Approve or reject the suggested changes.
8. Apply approved repairs.
9. Review the cleaned dataset.
10. Download the resulting CSV.

The original dataset should remain unchanged. Ambiguous recommendations should be reviewed rather than treated as guaranteed corrections.

## 🔐 Security and Data Integrity

DataJanitor should follow these principles:

- Do not commit `.env` files, credentials, or private API keys.
- Validate uploaded files and reject unsupported formats.
- Apply appropriate upload size limits.
- Never trust user-supplied filenames or file paths.
- Keep original data separate from repaired data.
- Require explicit approval before applying suggested corrections.
- Record repair decisions where audit logging is implemented.
- Avoid exposing sensitive dataset contents in logs or email reports.
- Review `.gitignore` before pushing the repository to GitHub.

**Important:** A detected anomaly is not necessarily an error. Statistical outliers and automatically suggested values should be reviewed in the context of the dataset.

## 🛠️ Troubleshooting

### Python or Uvicorn is not recognized

Ensure that Python is installed and available on your PATH. Activate the backend virtual environment and run:

```powershell
python -m uvicorn app.main:app --reload
```

### Virtual environment activation fails

Confirm that `.venv` exists inside `backend`. If it does not, create it using the setup instructions above.

### Port 8000 is already in use

Start the backend on another port:

```powershell
python -m uvicorn app.main:app --reload --port 8001
```

If you change the port, update the frontend API configuration accordingly.

### Port 5173 is already in use

Vite may automatically select another available port. Open the exact URL printed in the terminal.

### Frontend cannot connect to the backend

Check that:

- The backend is running.
- The frontend API URL points to the correct backend address.
- The backend's CORS configuration allows the frontend origin.
- Both terminals are free of startup errors.

### Database or SQLite errors

Check the configured database URL, write permissions, and database initialization logic. Do not delete the database file without backing it up if you need to preserve scan history.

### Dependency installation fails

Verify your Python and Node.js versions and inspect the complete error message. Avoid upgrading all dependencies indiscriminately, since that can introduce compatibility problems.

## 🌱 Future Improvements

Potential future enhancements include:

- More configurable data-quality rules.
- Improved detection of inconsistent records.
- More explainable repair recommendations.
- Expanded dataset formats and export options.
- Enhanced scan history and audit reporting.
- Additional validation and integration tests.
- Deployment support and optional multi-user authentication.

These are potential improvements, not a claim that every feature is currently implemented.

## 🤝 Contributing

Contributions, bug reports, and suggestions are welcome.

1. Fork the repository.
2. Create a feature branch.
3. Implement and test your changes.
4. Commit your changes with a descriptive message.
5. Open a pull request.

## 👨‍💻 Author

**Aahaan Singh**

GitHub: [@Aahaan14](https://github.com/Aahaan14)

Project: [DataJanitor](https://github.com/Aahaan14/DataJanitor)

## 📄 License

No license is specified here. Add a `LICENSE` file and update this section if you decide to distribute the project under an open-source license.
