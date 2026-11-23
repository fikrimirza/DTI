@echo off
rem AEP2cABR - buka GUI. Butuh Python 3.8+ (python.org, centang "Add to PATH").
cd /d "%~dp0"
where pythonw >nul 2>nul && (start "" pythonw -m aep2cabr gui) || (python -m aep2cabr gui)
