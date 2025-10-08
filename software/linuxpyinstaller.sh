rm -rf build
rm -rf dist

~/venv/bin/python3 -m PyInstaller HaasoscopeProQt.py

rm -rf ../../HaasoscopePro_Linux
mkdir ../../HaasoscopePro_Linux

mkdir "../../HaasoscopePro_Linux/adc board firmware"
mkdir "../../HaasoscopePro_Linux/adc board firmware/output_files"
cp "../adc board firmware/output_files/coincidence_auto.rpd" "../../HaasoscopePro_Linux/adc board firmware/output_files/"

mv dist/HaasoscopeProQt ../../HaasoscopePro_Linux/Linux_HaasoscopeProQt

cp *.ui ../../HaasoscopePro_Linux/Linux_HaasoscopeProQt/
cp icon.png ../../HaasoscopePro_Linux/Linux_HaasoscopeProQt/

rm -rf build
rm -rf dist

zip -rq ../../HaasoscopePro_Linux.zip ../../HaasoscopePro_Linux
mv ../../HaasoscopePro_Linux.zip ../../HaasoscopePro_Linux/
