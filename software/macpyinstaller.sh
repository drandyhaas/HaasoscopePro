rm -rf build
rm -rf dist

/usr/bin/python3 -m PyInstaller HaasoscopeProQt.py

mkdir ../../HaasoscopePro_dist
rm -rf ../../HaasoscopePro_dist/Mac_HaasoscopeProQt
mkdir ../../HaasoscopePro_dist/Mac_HaasoscopeProQt

rmdir /s /q "../../HaasoscopePro_dist/adc board firmware"
mkdir "../../HaasoscopePro_dist/adc board firmware"
mkdir "../../HaasoscopePro_dist/adc board firmware/output_files"
cp "../adc board firmware/output_files/coincidence_auto.rpd" "../../HaasoscopePro_dist/adc board firmware/output_files/"

mv dist/HaasoscopeProQt/HaasoscopeProQt.exe ../../HaasoscopePro_dist/Mac_HaasoscopeProQt/
mv dist/HaasoscopeProQt/_internal ../../HaasoscopePro_dist/Mac_HaasoscopeProQt/

cp *.ui ../../HaasoscopePro_dist/Mac_HaasoscopeProQt/
cp icon.png ../../HaasoscopePro_dist/Mac_HaasoscopeProQt/

rm -rf build
rm -rf dist
