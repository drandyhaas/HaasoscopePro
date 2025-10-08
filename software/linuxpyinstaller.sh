rm -rf build
rm -rf dist

~/venv/bin/python3 -m PyInstaller HaasoscopeProQt.py

rm -rf ../../HaasoscopePro_Mac
mkdir ../../HaasoscopePro_Mac

mkdir "../../HaasoscopePro_Mac/adc board firmware"
mkdir "../../HaasoscopePro_Mac/adc board firmware/output_files"
cp "../adc board firmware/output_files/coincidence_auto.rpd" "../../HaasoscopePro_Mac/adc board firmware/output_files/"

mv dist/HaasoscopeProQt ../../HaasoscopePro_Mac/Mac_HaasoscopeProQt

cp *.ui ../../HaasoscopePro_Mac/Mac_HaasoscopeProQt/
cp icon.png ../../HaasoscopePro_Mac/Mac_HaasoscopeProQt/

rm -rf build
rm -rf dist

zip -rq ../../HaasoscopePro_Mac.zip ../../HaasoscopePro_Mac
mv ../../HaasoscopePro_Mac.zip ../../HaasoscopePro_Mac/
