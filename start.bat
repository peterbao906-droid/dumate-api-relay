@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

REM ============================================================
REM  【必改】把下面两个 CHANGE_ME 换成你自己的随机强口令！
REM  生成方法：python -c "import secrets;print(secrets.token_urlsafe(24))"
REM  不改的话，同一网段任何人都能刷你的积分。
REM ============================================================
if "%API_TOKEN%"=="" set API_TOKEN=CHANGE_ME_API_TOKEN
if "%RELAY_TOKEN%"=="" set RELAY_TOKEN=CHANGE_ME_RELAY_TOKEN
REM ============================================================

if "%API_PORT%"=="" set API_PORT=8765
if "%RELAY_PORT%"=="" set RELAY_PORT=8000

echo ============================================
echo   DuMate 额度服务启动中
echo   API token   : %API_TOKEN%
echo   Relay token : %RELAY_TOKEN%
echo   端口        : API %API_PORT% / Relay %RELAY_PORT%
echo ============================================
echo.
echo 提示: DuMate 桌面版必须保持运行，否则调用会失败。
echo.

python start.py --api-token %API_TOKEN% --relay-token %RELAY_TOKEN% --api-port %API_PORT% --relay-port %RELAY_PORT%

if errorlevel 1 (
  echo.
  echo [启动失败] 常见原因:
  echo   1. 依赖没装: python -m pip install -r scripts\requirements.txt
  echo   2. DuMate 桌面版没运行（必须先打开并登录）
  echo   3. 端口 8765 / 8000 被占用
  echo   4. Python 不在 PATH 里，试试 py start.py 替代 python start.py
  echo.
  pause
)
