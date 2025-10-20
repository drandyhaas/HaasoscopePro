# For compiling firmware

Install Quartus Prime Lite (free)
 - Tested on Windows, but Linux should work too
 - Tested with version 23.1, but newer should also be OK

Open the **adc_board_firmware/coincidence.qpf** project file in this directory with Quartus Prime Lite
 - File... Open Project

If you've made changes to the code, recompile
 - Processing... Start Compilation (or the "play" button in the menu bar)

# To upload firmware using USB blaster

 - Attach power to board
 - Attach USB Blaster to board via JTAG (to set up the usb blaster see tips below)
 - Tools... Programmer
   - Hardware Setup... select USB blaster by double clicking, then close
   - (If you need permanent writing to the board flash, and have recompiled, remake the jic file by doing File... Convert Programming Files, then Open Conversion Setup Data..., select **adc_board_firmware/coincidence.cof**, then Generate button at bottom)
   - Add File... **adc_board_firmware/output_files/coincidence.sof** (for temporary testing) or **adc_board_firmware/output_files/coincidence.jic** (for permanent writing to the board flash memory)
   - Select checkbox Program/Configure
   - Start

### To setup USB Blaster on Windows:
 - After plugging in the USB Blaster, it may appear as an unrecognized device in the device manager. If so, you need to install a driver for it. Drivers come with the Quartus installation (even the "programmer only" version). Follow these instructions to install the driver:<br>
Plug in the USB blaster device, go to it in the device manager, and do Update driver, then Browse my computer for drivers, Let me pick from a list of devices, select JTAG cables, Have disk, and select the intelFPGA_lite\<version>\quartus\drivers\usb-blaster-ii directory, and install.

### To setup USB Blaster on Linux:
 - In theory it should work out of the box, but you just need permissions to access it. Try this and then plug it in: <code>sudo cp HaasoscopePro/software/blaster.rules /etc/udev/rules.d/</code>

### Tips in case of problems:
 - Maybe the USB-blaster must first be powered from the board and then connected to the PC. So the procedure step by step: connect the USB-Blaster to your board, power-on the board, plug the USB cable in the PC.

### Screenshots for temporary (sof) or permanent flash (jic) programming:

![Screenshot 2025-03-10 155821](https://github.com/user-attachments/assets/a48c5c72-e71a-4d7f-8bfe-ed48cdbfaf09)

![Screenshot 2025-03-10 155805](https://github.com/user-attachments/assets/000f7881-6075-42fd-b315-97af277fd60a)

# To upload firmware using Raspberry Pi

### Set up things

 - Power up the raspberry pi and log into it
 - Install openFPGALoader: https://github.com/trabucayre/openFPGALoader
 - For now you may still need the head version of the code and to compile it yourself - there is a [small change I committed](https://github.com/trabucayre/openFPGALoader/pull/584) which is only in release v1.0.0 onwards

### Connect things

 - The command to upload over JTAG will include "--pins 26:13:6:19" corresponding to the GPIOs to use for TDI:TDO:TCK:TMS
 - Given where those are on the JTAG connector on the Haasoscope Pro (which is standard for JTAG), we need raspberry pi pins 31 33 35 37 39 (corresponding to GPIO 26 13 6 19 and GND) going to JTAG pins 1 3 5 9 and 10, respectively, on the Haasoscope Pro

<img width="1110" height="800" alt="Pi Jtag" src="https://github.com/user-attachments/assets/664d550e-07a4-4639-9c5c-9c3b3b8295bd" />

### Upload
 
 - cd HaasoscopePro/adc\ board\ firmware
 - For temporary (SRAM) upload: <code>openFPGALoader -c libgpiod --pins 26:13:6:19 output_files/coincidence.rbf</code>
 - For permanent (flash) upload, first copy a [special bridge firmware](https://github.com/drandyhaas/spioverjtag) (used for writing to flash) to a place where openFPGALoader can find it:
   <br><code>sudo cp spiOverJtag_EP4CE30.rbf /usr/local/share/openFPGALoader/</code>
   <br>Then you can do the flash writing: <br><code>openFPGALoader -c libgpiod --pins 26:13:6:19 --fpga-part EP4CE30 -f output_files/coincidence.rbf</code>
