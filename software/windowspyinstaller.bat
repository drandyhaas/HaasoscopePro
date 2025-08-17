python -m PyInstaller HaasoscopeProQt.py
cd dist
move HaasoscopeProQt\HaasoscopeProQt.exe Windows_HaasoscopeProQt\
rmdir /s /q Windows_HaasoscopeProQt\_internal
move HaasoscopeProQt\_internal Windows_HaasoscopeProQt\
rmdir /q HaasoscopeProQt
cd ..
rmdir /s /q build
copy *.ui dist\Windows_HaasoscopeProQt\
copy icon.png dist\Windows_HaasoscopeProQt\
