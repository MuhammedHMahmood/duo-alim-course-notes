@echo off
REM ============================================================
REM DUO Class Notes — Weekly Pipeline
REM Run this whenever you're at your PC to fetch, transcribe,
REM generate notes, build the site, and push to GitHub.
REM ============================================================

cd /d "C:\Users\moham\Documents\DUO Class Notes"

echo.
echo ========================================
echo  DUO Pipeline — %date% %time%
echo ========================================
echo.

REM --- Step 1: Fetch new recordings from Google Drive ---
echo [1/6] Fetching new recordings...
python duo.py fetch --active-only
if errorlevel 1 (
    echo ERROR: Fetch failed. Continuing anyway...
)

REM --- Step 2: Transcribe new videos with Whisper ---
echo.
echo [2/6] Transcribing new videos...
python duo.py transcribe --active-only
if errorlevel 1 (
    echo ERROR: Transcription failed. Continuing anyway...
)

REM --- Step 3: Generate notes via Claude CLI ---
echo.
echo [3/6] Generating study notes...
python duo.py notes --active-only --workers 4
if errorlevel 1 (
    echo ERROR: Note generation failed. Continuing anyway...
)

REM --- Step 4: Build MkDocs site ---
echo.
echo [4/6] Building MkDocs site...
python duo.py build
if errorlevel 1 (
    echo ERROR: Build failed. Stopping.
    goto :done
)

REM --- Step 5: Git commit ---
echo.
echo [5/6] Committing changes...
git add docs/ mkdocs.yml subjects/*/notes/ scripts/ duo.py run_pipeline.bat .gitignore
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "Update notes — %date%"
    echo Committed.
) else (
    echo No changes to commit.
)

REM --- Step 6: Push to GitHub ---
echo.
echo [6/6] Pushing to GitHub...
git push origin main
if errorlevel 1 (
    echo ERROR: Push failed. You may need to pull first.
) else (
    echo Pushed successfully.
)

:done
echo.
echo ========================================
echo  Pipeline complete!
echo ========================================
echo.
python duo.py status
pause
