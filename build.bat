@echo off

for /f "delims=" %%i in ('python -c "import glfw,os; print(os.path.dirname(glfw.__file__))"') do set GLFW_DIR=%%i
for %%f in (glfw3.dll msvcr120.dll) do if exist "%GLFW_DIR%\%%f" copy "%GLFW_DIR%\%%f" . >nul

python -m PyInstaller --onefile --noconsole --noupx --name "OffsetSuggester" ^
  --copy-metadata slimgui ^
  --add-binary "glfw3.dll;glfw" ^
  --add-binary "msvcr120.dll;glfw" ^
  src/main.py

if %ERRORLEVEL% equ 0 (
    for %%i in (dist\OffsetSuggester.exe) do echo Built: %%~zi bytes
) else (
    echo Build failed
)
pause
