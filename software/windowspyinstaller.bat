rmdir /s /q build
rmdir /s /q  dist

python -m PyInstaller HaasoscopeProQt.py

mkdir ..\..\HaasoscopePro_dist
rmdir /s /q ..\..\HaasoscopePro_dist\Windows_HaasoscopeProQt
mkdir ..\..\HaasoscopePro_dist\Windows_HaasoscopeProQt

rmdir /s /q "..\..\HaasoscopePro_dist\adc board firmware"
mkdir "..\..\HaasoscopePro_dist\adc board firmware"
mkdir "..\..\HaasoscopePro_dist\adc board firmware\output_files"
copy "..\adc board firmware\output_files\coincidence_auto.rpd" "..\..\HaasoscopePro_dist\adc board firmware\output_files\"

move dist\HaasoscopeProQt\HaasoscopeProQt.exe ..\..\HaasoscopePro_dist\Windows_HaasoscopeProQt\
move dist\HaasoscopeProQt\_internal ..\..\HaasoscopePro_dist\Windows_HaasoscopeProQt\

copy *.ui ..\..\HaasoscopePro_dist\Windows_HaasoscopeProQt\
copy icon.png ..\..\HaasoscopePro_dist\Windows_HaasoscopeProQt\

rmdir /s /q build
rmdir /s /q  dist
