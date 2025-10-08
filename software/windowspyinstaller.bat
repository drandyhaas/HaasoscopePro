rmdir /s /q build
rmdir /s /q dist

python -m PyInstaller HaasoscopeProQt.py

rmdir /s /q ..\..\HaasoscopePro_Windows
mkdir ..\..\HaasoscopePro_Windows

mkdir "..\..\HaasoscopePro_Windows\adc board firmware"
mkdir "..\..\HaasoscopePro_Windows\adc board firmware\output_files"
copy "..\adc board firmware\output_files\coincidence_auto.rpd" "..\..\HaasoscopePro_Windows\adc board firmware\output_files\"

move dist\HaasoscopeProQt ..\..\HaasoscopePro_Windows\Windows_HaasoscopeProQt

copy *.ui ..\..\HaasoscopePro_Windows\Windows_HaasoscopeProQt\
copy icon.png ..\..\HaasoscopePro_Windows\Windows_HaasoscopeProQt\

rmdir /s /q build
rmdir /s /q  dist

powershell Compress-Archive -Path "..\..\HaasoscopePro_Windows" -DestinationPath "..\..\HaasoscopePro_Windows\HaasoscopePro_Windows.zip"
