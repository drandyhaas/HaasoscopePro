# Haasoscope Pro ADC/FPGA Board

This is the main ADC and FPGA board for the Haasoscope Pro - a 2 GHz 3.2 GS/s 12-bit open-source USB oscilloscope.

![Board Layout](haasoscope_pro_adc_fpga_board.png)

## Overview

The Haasoscope Pro ADC board is a high-performance data acquisition board featuring dual-channel analog-to-digital conversion with FPGA processing and USB connectivity. The board integrates the complete signal chain from analog inputs through digitization, processing, and USB transfer.

## Key Specifications

- **Bandwidth**: 2 GHz
- **Sample Rate**: Up to 3.2 GS/s (interleaved) or 1.6 GS/s per channel
- **Resolution**: 12-bit
- **Channels**: 2 analog input channels
- **Interface**: USB 2.0 (FT232HQ)
- **FPGA**: Intel/Altera Cyclone IV EP4CE30F23C6N
- **Power**: 5-24V DC input with multiple onboard regulators

## Major Components

### Data Acquisition
- **ADC12DL2500ACF** (U2): Texas Instruments 12-bit dual 2.5GSPS or single 5GSPS ADC with LVDS interface
  - Datasheet: [adc12dl2500.pdf](adc12dl2500.pdf)

### Signal Conditioning (per channel)
- **OPA859IDSGR** (FL1-FL4): High-speed operational amplifiers for input buffering
- **LMH5401IRMST** (IC13, IC21): 6.2 GHz differential amplifiers
- **LMH6401IRMZR** (IC14, IC29): Programmable gain amplifiers (PGA) with 4.5 GHz bandwidth

### Processing & Control
- **EP4CE30F23C6N** (IC5): Cyclone IV FPGA (484-pin FBGA)
  - 28,848 logic elements
  - 1,803 embedded memory blocks
  - Configuration flash: EPCQ16ASI8N (IC6)
  - Custom firmware in [../adc board firmware](../adc%20board%20firmware/)

### Clock Generation
- **ADF4350BCPZ** (U2): 4.4 GHz PLL/frequency synthesizer for ADC clock generation
- **Y2**: 50 MHz reference oscillator
- **Y3**: 12 MHz crystal for USB interface

### USB Interface
- **FT232HQ** (IC8): FTDI USB 2.0 high-speed interface chip
  - Configuration EEPROM: 93LC56B (IC9)

### Auxiliary Features
- **DAC8562SDGSR** (IC17): Dual-channel 16-bit DAC for offset/gain control
- **ADC122S021CIMM** (IC3): 12-bit ADC for temperature and voltage monitoring
- **G6K-2F-RF** (K1-K5): Omron RF relays for input switching
- **TLP3475** (K6-K7): PhotoMOS solid-state relays
- **WS2812-2020** (U1, U3): RGB LED indicators

### Power Management
- **LMR33630ADDA** (PS2, PS9-PS14): 3A step-down DC-DC converters (7 total)
- **TPS7A7200RGTR** (IC7, IC22-IC28): 2A low-dropout linear regulators
- **TPS72325DBVR** (IC10, IC25): 2.5V precision LDO regulators
- Multiple voltage rails: 3.3V, 2.5V, 1.2V, and adjustable rails

## Design Files

### Eagle CAD Files (v9.6.2)
- **haasoscope_pro_adc_fpga_board.sch**: Main schematic
- **haasoscope_pro_adc_fpga_board.brd**: PCB layout (10-layer board)
- **Component Libraries**:
  - ADC12DL2500ACF.lbr
  - EP4CE30F23C6N.lbr
  - EPCQ16ASI8N.lbr
  - SN74AVC4T774PWR.lbr
  - NFM31PC276B0J3L.lbr
  - EEE-FT1E102UP.lbr
  - WS2812-2020.lbr
  - ADC102S021CIMM_NOPB.lbr

### KiCad Files
- **Kicad/**: KiCad conversion of the design files

### Documentation
- **haasoscope_pro_adc_fpga_board_schematics.pdf**: Complete schematic in PDF format
- **haasoscope_pro_adc_fpga_board_routing.png**: PCB routing visualization
- **haasoscope_pro_adc_fpga_board.png**: Board layout image

### Manufacturing Files
- **haasoscope_pro_adc_fpga_board_2025-03-11.zip**: Gerber files for PCB fabrication
- **haasoscope_pro_adc_fpga_board_bom.csv**: Bill of materials for JLCPCB assembly
- **haasoscope_pro_adc_fpga_board_cpl.csv**: Component placement file
- **bom.csv** / **bom.xlsx**: Detailed bill of materials with part numbers and suppliers
- **jlcpcb_parts_output.csv**: JLCPCB part mapping
- **jlcpcb_parts_scraper.py**: Python script for JLCPCB parts database

### CAM Files
- Use [../jlcpcb_10_layer_v9_haas.cam](../jlcpcb_10_layer_v9_haas.cam) for generating Gerbers
- Design rules: [../jlcpcb-10layers-haas.dru](../jlcpcb-10layers-haas.dru)

## Bill of Materials Summary

The board contains approximately:
- **320+ capacitors** (0402/0603/0805 sizes, plus 1000µF electrolytics for power)
- **240+ resistors** (primarily 0402/0201 sizes)
- **30+ ICs** (amplifiers, regulators, FPGA, ADC, etc.)
- **25+ inductors** (power and RF chokes)
- **18 LEDs** (status indicators plus 2 RGB LEDs)
- **7 switches/relays** (5 RF relays, 2 tactile switches)

### Key Off-Board Components
- 2× BNC connectors (Molex 73100-0105) for analog inputs
- 2× USB Type-A connectors (TE 292303-1)
- 2× Ethernet RJ45 jacks (Amphenol FRJAE-438)
- 3× SMA edge connectors (for clock/reference signals)
- 1× USB Type-C connector (for power/data)
- 1× DC power jack (PJ-002AH, 12V input)
- 1× 2x5 JTAG connector for FPGA programming
- 1× 5V 40×40×10mm cooling fan with JST connector
- 2× Light pipes (BIVAR SLP3-150-100-F)
- 2× 20×20×10mm heatsinks
- Enclosure: Hammond 1455R2201 (165×30.5×220mm aluminum extrusion)

## PCB Specifications

- **Layers**: 10-layer stackup
- **Dimensions**: Approximately 165×220mm (fits Hammond 1455R2201 case)
- **Technology**:
  - Minimum trace/space optimized for high-speed signals
  - Controlled impedance for RF traces
  - Multiple ground/power planes
  - Via stitching for EMI control
- **Manufacturer**: Designed for JLCPCB 10-layer process

## Power Requirements

- **Input voltage**: 5-24V DC (recommended: 12V 2A minimum)
- **USB Power**: USB Type-C (5V, up to 2A)
- **Consumption**: Approximately 10W, with ADC running at 3.2 GHz

## Assembly Notes

1. The board uses SMD components down to 0201 size - professional assembly recommended
2. FPGA requires proper thermal management (heatsink + fan)
3. High-speed ADC sections require careful assembly to maintain signal integrity
4. Multiple voltage regulators must be populated in correct sequence
5. USB EEPROM (93LC56B) should be programmed with configuration (see ftdi_template_haasoscopepro.xml in parent directory)

## Programming & Firmware

- **FPGA Programming**: Via JTAG connector using Quartus Programmer
- **Firmware**: See [../adc board firmware](../adc%20board%20firmware/) directory
- **USB Configuration**: Use FT_Prog tool with ftdi_template_haasoscopepro.xml template

## Testing & Calibration

The board includes:
- Temperature sensor (NCP18WF104F03RC thermistor at R207)
- Voltage monitoring via ADC122S021
- RGB status LEDs for operational feedback
- Multiple test points for voltage verification

## License

See [LICENSE](../LICENSE) file in the repository root.

## Design History

- Latest revision: 2025-03-11
- Original design based on Eagle 9.6.2
- Multiple board revisions with continuous improvements

## Related Documentation

- Main project repository: [../README.md](../README.md)
- Firmware documentation: [../adc board firmware](../adc%20board%20firmware/)
- Software/GUI: [../software](../software/)
- Case design: [../case](../case/)

## Resources

- [Product Page on CrowdSupply](https://www.crowdsupply.com/andy-haas/haasoscope-pro)
- [Available at Mouser](https://www.mouser.com/c/?q=Haasoscope)
- [Hackaday.io Project](https://hackaday.io/project/200773-haasoscope-pro)
- [Video Tutorials](https://www.youtube.com/playlist?list=PLB1iz3MRh5DiKQQmUUNoTf2oo_m5qS00k)

## Support

For questions and support, see the main repository or visit the project pages listed above.
