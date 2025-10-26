# Haasoscope Pro Case Panels

This directory contains the PCB panel designs for the front and back panels of the Haasoscope Pro aluminum case.

## Panel Design Files

### Front Panel
- `front panel.sch` - Eagle schematic for the front panel
- `front panel.brd` - Eagle board layout for the front panel
- `front panel_2025-02-23.zip` - Latest production files (gerbers/drill files)
- `front panel_2025-01-31.zip` - Previous version

The front panel includes connectors and indicators for user interface elements.

### Back Panel
- `back panel.sch` - Eagle schematic for the back panel
- `back panel.brd` - Eagle board layout for the back panel
- `back panel_2025-02-23.zip` - Latest production files (gerbers/drill files)
- `back panel_2025-01-31.zip` - Previous version

The back panel includes I/O connectors and power interfaces.

## Component Datasheets

The directory includes PDF datasheets for the connectors and components used on the panels:

- `1455R2201BU.pdf` - Case/enclosure datasheet
- `2212071830_HCTL-HC-TYPE-C-16P-CH3-18-3A-02_C5307756.pdf` - USB Type-C connector
- `628f655577fda929DS_CON_EDGE_SMA_5-3049320.pdf` - Edge-mount SMA connector
- `6941xx301002.pdf` - Connector datasheet
- `731000105_sd.pdf` - Connector datasheet
- `Bivar_SLP3_150_XXX_X_N-3318840.pdf` - LED light pipe
- `ENG_CD_292303_G-2061405.pdf` - Connector datasheet

## Eagle Library Files

- `725996-2.lbr` - Custom component library
- `SLP3-150-100-F.lbr` - LED light pipe library

## Manufacturing

The latest production-ready files are in the dated `.zip` archives. Use the most recent version for manufacturing:
- Front panel: `front panel_2025-02-23.zip`
- Back panel: `back panel_2025-02-23.zip`

These can be sent directly to a PCB manufacturer that supports custom panel designs.

## Design Software

The panel designs were created using **Autodesk Eagle 9.6.2**. You can open the `.sch` and `.brd` files with Eagle to view or modify the designs.
