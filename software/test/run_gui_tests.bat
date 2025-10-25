@echo off
REM GUI Test Runner for HaasoscopeProQt
REM This batch file makes it easy to run various GUI tests on Windows
REM Run from the test directory

echo.
echo ================================================================================
echo  HaasoscopeProQt GUI Test Runner
echo ================================================================================
echo.

:menu
echo Please select a test to run:
echo.
echo  1. Quick Demo (simple 8-second test with screenshot)
echo  2. Standalone Test (basic smoke test)
echo  3. Create Baseline Screenshots
echo  4. Run Automated Tests (compare to baseline)
echo  5. Run pytest Suite (comprehensive tests)
echo  6. Install Test Dependencies
echo  7. Exit
echo.

set /p choice="Enter your choice (1-7): "

if "%choice%"=="1" goto demo
if "%choice%"=="2" goto standalone
if "%choice%"=="3" goto baseline
if "%choice%"=="4" goto automated
if "%choice%"=="5" goto pytest
if "%choice%"=="6" goto install
if "%choice%"=="7" goto end

echo Invalid choice. Please try again.
echo.
goto menu

:demo
echo.
echo Running Quick Demo Test...
echo.
python demo_gui_test.py
pause
goto menu

:standalone
echo.
echo Running Standalone Test...
echo.
python test_gui_standalone.py --duration 10
pause
goto menu

:baseline
echo.
echo Creating Baseline Screenshots...
echo.
python test_gui_automated.py --baseline --verbose
pause
goto menu

:automated
echo.
echo Running Automated Tests (comparing to baseline)...
echo.
python test_gui_automated.py --verbose
pause
goto menu

:pytest
echo.
echo Running pytest Test Suite...
echo.
pytest test_gui.py -v
pause
goto menu

:install
echo.
echo Installing Test Dependencies...
echo.
pip install -r test_requirements.txt
echo.
echo Installation complete!
pause
goto menu

:end
echo.
echo Exiting...
echo.
