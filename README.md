## HaasoscopePro

### An Affordable 2 GHz 3.2 GS/s 12 bit open-source open-hardware expandable USB oscilloscope

### [Available on CrowdSupply](https://www.crowdsupply.com/andy-haas/haasoscope-pro) and at [Mouser](https://www.mouser.com/c/?q=Haasoscope)

### [Hackaday.io Page](https://hackaday.io/project/200773-haasoscope-pro)

![haasoscope_pro_adc_fpga_board.png](adc%20board%2Fhaasoscope_pro_adc_fpga_board.png)

#### Schematics in PDF: [haasoscope_pro_adc_fpga_board_schematics.pdf](adc%20board%2Fhaasoscope_pro_adc_fpga_board_schematics.pdf)

#### Routing image: [haasoscope_pro_adc_fpga_board_routing.png](adc%20board%2Fhaasoscope_pro_adc_fpga_board_routing.png)

#### Firmware overview: [firmware schematic.pdf](adc%20board%20firmware/schematic.pdf)

### Video tutorials

See this [YouTube Playlist](https://www.youtube.com/playlist?list=PLB1iz3MRh5DiKQQmUUNoTf2oo_m5qS00k) !

### Versions

- v27 is the firmware that shipped with the first round of units, found in the "main" branch
- v28 is the latest firmware, and software development is also happening in the "v28fixtrigger" branch
- to use a different branch, do <code>git pull && git checkout "branchname"</code> or select the branch name in the drop down box on github and then download the zip file of the code, then run the new software, update the firmware on your board from that new software, and power cycle the board

### Quick start (Windows/Mac)

1) [Download code](https://github.com/drandyhaas/HaasoscopePro/archive/refs/heads/main.zip) and unzip it (or another zip file version like [v28fixtrigger](https://github.com/drandyhaas/HaasoscopePro/archive/refs/heads/v28fixtrigger.zip))
2) Rename directory HaasoscopePro-main to HaasoscopePro (for consistency with git below)
3) Install [FTDI D2xx driver](https://ftdichip.com/drivers/d2xx-drivers/) 
- for Windows: install by running the setup exe at <code>HaasoscopePro/software/ftdi_setup.exe</code>
- for Mac: <code>sudo mkdir -p /usr/local/lib; sudo cp HaasoscopePro/software/libftd2xx.dylib /usr/local/lib/</code> 
- for Linux: <code>sudo cp HaasoscopePro/software/libftd2xx.so /usr/lib/</code>
4) Plug Haasoscope Pro into your computer via USB
5) Run **HaasoscopeProQt** in the <code>HaasoscopePro/software/dist/(OS)_HaasoscopeProQt</code> directory

### Fuller way of running (Windows/Mac/Linux)

1) Install python3 and git for your operating system
2) Install dependencies: <br><code>pip3 install numpy scipy pyqtgraph PyQt5 pyftdi matplotlib ftd2xx</code>
3) Get code: <br><code>git clone https://github.com/drandyhaas/HaasoscopePro.git</code>
4) Install FTDI driver (see Quick start above)
5) Plug Haasoscope Pro into your computer via USB
6) Run:
<br><code>cd HaasoscopePro/software</code>
<br><code>python3 HaasoscopeProQt.py</code>

### Tips

- If not enough power is supplied or issues happen during readout, plug in via a powered USB hub, a USB-A to C cable, or use an external 12V power adapter
- If you get security issues on Mac, do: <code>xattr -cr Mac_HaasoscopeProQt</code>
- If the board is not found on Linux, use this udev rule and then plug it in: <code>sudo cp HaasoscopePro/software/ft245.rules /etc/udev/rules.d/</code>
- If you get an error like "qt.qpa.plugin: Could not load the Qt platform plugin "xcb" in "" even though it was found", try: <code>sudo apt install libxcb-xinerama0</code>

### To remake exe for quick start
1) <code>pip3 install pyinstaller</code>
2) <code>cd HaasoscopePro/software</code>
3) <code>.\windowspyinstaller.bat</code> or <code>./macpyinstaller.sh</code>

### Repository structure

- [adc board](adc%20board/): Design files and documentation for the main board, based on Eagle 9.6.2
- [adc board/Kicad](adc%20board/Kicad): An import of the main board design files into KiCad 8
- [adc board firmware](adc%20board%20firmware/): Quartus lite project for the Altera Cyclone IV FPGA firmware (see [README](adc%20board%20firmware/README.md) in there for more info)
- [case](case/): Front and back PCB panels for the aluminum case
- [software](software/): Python files for the oscilloscope program
- [sub boards](sub%20boards/): Eagle design files and documentation for smaller test boards that were used during development 

### 2 GHz Active Probe

All designs for the accompanying active probe are in a separate [repository](https://github.com/drandyhaas/oshw-active-probe)

### Editing the GUI

The Haasoscope Pro GUI can be edited using [Qt Designer](https://www.pythonguis.com/installation/install-qt-designer-standalone/), on software/HaasoscopePro.ui or HaasoscopeProFFT.ui etc.

### Other GUIs

1) [HaasoscopeProGUI](https://github.com/priimak/HaasoscopeProGUI) is a PyQt6-based GUI aimed to provide a professional look and experience, but may not have all the latest features, like multi-scope support, oversampling, etc.
2) [ngscopeclient](https://www.ngscopeclient.org/) is a very powerful multi-instrument analysis suite. HaasoscopeProQt must be running, which then automatically opens the LAN port and accepts connections from ngscopeclient. See the ngscopeclient user manual for details.

