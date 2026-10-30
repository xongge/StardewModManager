@echo off
rem One-click upload to GitHub. Requires git for Windows.
setlocal
cd /d "%~dp0"
set "REPO=https://github.com/xongge/StardewModManager.git"
set "MSG=chore: release v1.4.2"

where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Git not found. Install it first: https://git-scm.com/download/win
  pause
  exit /b 1
)

if not exist ".git" (
  echo === git init ===
  git init
  git branch -M main
)

git config user.name >nul 2>nul || git config user.name "xongge"
git config user.email >nul 2>nul || git config user.email "xongge@users.noreply.github.com"

echo === staging files ===
git add -A
git status --short

echo === commit ===
git commit -m "%MSG%"
if errorlevel 1 echo (nothing new to commit, or commit failed - see message above)

echo === remote ===
git remote remove origin >nul 2>nul
git remote add origin %REPO%

echo === push ===
git push -u origin main
if errorlevel 1 (
  echo.
  echo Remote already has commits. Trying: git pull --rebase origin main ...
  git pull --rebase origin main
  if errorlevel 1 (
    git rebase --abort >nul 2>nul
    echo.
    echo [HINT] Rebase did not work automatically ^(probably conflicting files^).
    echo        If you want THIS folder to fully replace the remote content, run:
    echo            git push -u origin main --force
  ) else (
    git push -u origin main
  )
)
if errorlevel 1 (
  echo.
  echo [HINT] If authentication failed, use a Personal Access Token as the password:
  echo        https://github.com/settings/tokens
)
echo.
echo Done. Open https://github.com/xongge/StardewModManager
pause
