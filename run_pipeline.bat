@echo off
REM DUO Class Notes Weekly Pipeline
REM Run via Windows Task Scheduler
REM API keys are stored securely in Windows Credential Manager

cd /d "C:\Users\moham\Documents\DUO Class Notes"

REM Activate virtual environment if using one:
REM call .venv\Scripts\activate.bat

python scripts\pipeline.py
