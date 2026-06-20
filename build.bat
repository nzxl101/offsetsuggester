@echo off
for /f "delims=" %%i in ('python -c "import glfw,os; print(os.path.dirname(glfw.__file__))"') do set GLFW_DIR=%%i
python -m PyInstaller --onefile --noconsole --name "OffsetSuggester" ^
  --copy-metadata slimgui ^
  --add-binary "%GLFW_DIR%\glfw3.dll;glfw" ^
  --add-binary "%GLFW_DIR%\msvcr120.dll;glfw" ^
  src/main.py
if %ERRORLEVEL% equ 0 (
  echo Built: dist\OffsetSuggester.exe
) else (
  echo Build failed
)
pause
