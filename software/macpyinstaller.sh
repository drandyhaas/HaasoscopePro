rm -rf build
rm -rf dist

python3 -m PyInstaller HaasoscopeProQt.py
python3 -m PyInstaller dummy_scope/dummy_server.py

rm -rf ../../HaasoscopePro_Mac
mkdir ../../HaasoscopePro_Mac

mkdir "../../HaasoscopePro_Mac/adc board firmware"
mkdir "../../HaasoscopePro_Mac/adc board firmware/output_files"
cp "../adc board firmware/output_files/coincidence_auto.rpd" "../../HaasoscopePro_Mac/adc board firmware/output_files/"

mv dist/HaasoscopeProQt ../../HaasoscopePro_Mac/Mac_HaasoscopeProQt
mv dist/dummy_server/dummy_server ../../HaasoscopePro_Mac/Mac_HaasoscopeProQt/

cp *.ui ../../HaasoscopePro_Mac/Mac_HaasoscopeProQt/
cp icon.png ../../HaasoscopePro_Mac/Mac_HaasoscopeProQt/
cp libftd2xx.dylib ../../HaasoscopePro_Mac/Mac_HaasoscopeProQt/

rm -rf build
rm -rf dist

ditto -c -k --sequesterRsrc --keepParent ../../HaasoscopePro_Mac ../../HaasoscopePro_Mac.zip
mv ../../HaasoscopePro_Mac.zip ../../HaasoscopePro_Mac/
