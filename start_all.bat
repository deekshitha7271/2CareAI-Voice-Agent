@echo off
echo Starting Clinical Voice AI Agent Backend (FastAPI)...
start cmd /k "cd backend && call venv\Scripts\activate.bat && uvicorn api.server:app --reload"

echo Starting Clinical Voice AI Agent Frontend (React/Vite)...
start cmd /k "cd frontend && npm run dev"




