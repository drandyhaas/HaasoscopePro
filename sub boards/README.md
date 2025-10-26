# Sub Boards

This directory contains Eagle design files and documentation for smaller test boards that were developed during the Haasoscope Pro design process. These boards were used to test and validate individual subsystems before integration into the final main ADC/FPGA board.

## Board Descriptions

### Clock Board
Test board for the clock generation and distribution circuitry using the ADF4350 PLL frequency synthesizer. This board validates the high-frequency clock signals needed for the ADC sampling system.

**Key Components:**
- ADF4350 PLL synthesizer
- Reference materials and datasheets

### Data Board
Test board for data handling and buffering circuits.

### Eval Board
Evaluation board for testing component configurations and interfaces.

### FPGA Board
Test board for the Altera Cyclone IV FPGA (EP4CE10/EP4CE30) and its associated support circuitry including configuration memory (EPCQ16).

**Key Components:**
- EP4CE30F23C6N FPGA
- EPCQ16ASI8N configuration memory
- Pin definition spreadsheets
- Cyclone IV datasheets and documentation

### Input Board
Test board for the analog input signal conditioning path, including differential amplifiers, variable gain stages, and DAC-controlled offset circuits.

**Key Components:**
- LMH5401/LMH6401 differential amplifiers
- OPA693 operational amplifier
- DAC8562 dual 16-bit DAC
- TLV9102 op-amp

### Logo Board
Simple board design containing the Haasoscope logo artwork for branding purposes.

### Power Board
Test board for power regulation and distribution, including multiple voltage rail generation from 5V input or higher voltage DC input.

**Key Components:**
- LMR33630 buck converter
- TPS5430 buck converter
- TPS7A7200 low-noise LDO regulator
- TPS72325 LDO regulator

### Preinput Board
Test board for the front-end input signal conditioning before the main input amplifier stage.

## File Types

Each board directory typically contains:

- **`.sch`** - Eagle schematic files
- **`.brd`** - Eagle board layout files
- **`_bom.csv`** - Bill of Materials (component list)
- **`_cpl.csv`** - Component Placement List (pick-and-place data)
- **`.lbr`** - Eagle component library files
- **`.pdf`** - Component datasheets and reference documentation
- **`.zip`** - Exported Gerber/manufacturing files (when available)

## Design Software

All board files were created using **Eagle 9.6.2** (or compatible versions).

## Purpose

These test boards allowed individual subsystems to be:
- Prototyped and tested independently
- Validated before committing to the main board design
- Used for troubleshooting and characterization
- Referenced during main board development

The lessons learned from these test boards were incorporated into the final Haasoscope Pro main board design found in the `adc board/` directory.
