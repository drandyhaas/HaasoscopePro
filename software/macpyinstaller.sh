export MACOSX_DEPLOYMENT_TARGET=12.0 # Target macOS Monterey
/usr/bin/python3 -m PyInstaller HaasoscopeProQt.py
cd dist
rm -rf Mac_HaasoscopeProQt/HaasoscopeProQt
rm -rf Mac_HaasoscopeProQt/_internal
mv HaasoscopeProQt/* Mac_HaasoscopeProQt
rmdir HaasoscopeProQt
cd ..
rm -rf build
cp *.ui icon.png dist/Mac_HaasoscopeProQt/
