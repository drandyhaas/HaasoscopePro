rm -rf build
rm -rf dist

/usr/bin/python3 -m PyInstaller HaasoscopeProQt.py

rm -rf ../../HaasoscopePro_Mac
mkdir ../../HaasoscopePro_Mac

mkdir "../../HaasoscopePro_Mac/adc board firmware"
mkdir "../../HaasoscopePro_Mac/adc board firmware/output_files"
cp "../adc board firmware/output_files/coincidence_auto.rpd" "../../HaasoscopePro_Mac/adc board firmware/output_files/"

mv dist/HaasoscopeProQt ../../HaasoscopePro_dist/Mac_HaasoscopeProQt

cp *.ui ../../HaasoscopePro_dist/Mac_HaasoscopeProQt/
cp icon.png ../../HaasoscopePro_dist/Mac_HaasoscopeProQt/

rm -rf build
rm -rf dist

tar -a -c -f "..\..\HaasoscopePro_Mac\HaasoscopePro_Mac.zip" "..\..\HaasoscopePro_Mac"
