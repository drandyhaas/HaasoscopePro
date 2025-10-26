# Firmware Architecture

This section documents how the Haasoscope Pro ADC board firmware works.

## Overview

The firmware runs on an **Intel/Altera Cyclone IV E FPGA** (EP4CE30F23C6) and implements a real-time data acquisition system with the following key features:
- **LVDS high-speed serial interface** (800 Mbps) for ADC data
- **USB 2.0 control and data transfer** via FT232H chip
- **Advanced triggering system** with sub-sample precision
- **Multi-board synchronization** via LVDS trigger chain
- **Flexible downsampling** and averaging (1× to 40×)

**Current Firmware Version:** 31

## System Block Diagram

```
ADC Chips (4 channels × 14-bit LVDS @ 800 Mbps)
    ↓
LVDS Receivers & Deserializers (10:1 deserialization)
    ↓
Downsampler (40 samples/clock, channel formatting, decimation)
    ↓
Triggerer (threshold detection, state machine, RAM write control)
    ↓
RAM Buffer (1024 × 560-bit dual-port circular buffer)
    ↓
Command Processor (USB interface, waveform readout)
    ↓
FTDI 245-FIFO Controller (AXI-stream to USB)
    ↓
FT232H USB 2.0 Chip → PC Software
```

## Main Components

### 1. LVDS Receivers (lvds1.v, lvds2.v, etc.)
- **Purpose:** Convert LVDS analog signals from ADC chips to digital data
- **Configuration:** 4 independent receivers, 14-bit parallel output per receiver
- **Data Rate:** 800 Mbps input → 140-bit parallel output (10:1 deserialization)
- **Technology:** Altera ALTLVDS_RX with DPA (Dynamic Phase Alignment) for clock recovery
- **Clock Domain:** LVDS sample clock (100 MHz)

### 2. Downsampler (downsampler.v)
- **Purpose:** Organize deserialized data into samples, apply channel formatting, and perform decimation
- **Input:** 4 × 140-bit LVDS data (560 bits total)
- **Processing:**
  - Extracts 40 individual 12-bit ADC samples per clock cycle
  - Applies channel configuration (single/dual/oversampling modes)
  - Performs programmable downsampling (1×, 2×, 4×, 8×, 20×, 40×)
  - Optional high-resolution averaging (sums multiple samples for 12-20 bit precision)
- **Output:** 560-bit wide data containing 40 samples × 14 bits (12-bit data + 2-bit metadata)
- **Clock:** 100 MHz LVDS clock

### 3. Triggerer (triggerer.v)
- **Purpose:** Implements the trigger detection system and controls RAM write operations
- **Key States:**
  - State 0: Ready (waiting for trigger)
  - States 1-2: Threshold comparison (rising/falling edge)
  - States 5-7: External/auto triggers
  - State 200: Pre-acquisition (collecting pre-trigger samples)
  - State 250: Post-trigger acquisition
  - State 251: Data ready for readout
- **Trigger Types:**
  - Type 1: Threshold rising edge
  - Type 2: Threshold falling edge
  - Type 3: External LVDS trigger (from another board)
  - Type 4: Auto trigger (periodic forced capture)
  - Type 5: External SMA trigger (back panel input)
  - Type 30: LVDS trigger with echo-back (for time measurement)
- **Features:**
  - Programmable upper/lower thresholds (12-bit signed)
  - Time-of-Threshold (ToT) gating to prevent false triggers
  - Pre/post trigger capture (configurable sample counts)
  - Rolling trigger mode (~10 Hz when armed but not triggered)
  - Trigger phase detection (records which of 40 samples triggered)
  - Multi-board synchronization via LVDS trigger I/O
- **Clock:** 100 MHz LVDS clock

### 4. RAM Buffer (rambuffer.v)
- **Purpose:** Store captured ADC waveforms during acquisition
- **Capacity:** 1024 locations × 560 bits = 655 kB
- **Write Port:** LVDS clock domain (100 MHz), controlled by triggerer
- **Read Port:** Main clock domain (50 MHz), controlled by command processor
- **Technology:** Altera altsyncram (dual-port synchronous RAM)
- **Organization:** Circular buffer, each location holds 40 samples

### 5. Command Processor (command_processor.v)
- **Purpose:** Main control module - receives USB commands, configures system, reads out data
- **Clock:** 50 MHz main clock
- **Interfaces:**
  - USB AXI-stream input: 8-bit command reception
  - USB AXI-stream output: 32-bit data transmission
  - SPI master control for ADC configuration
  - PLL phase adjustment control
  - Flash memory interface for firmware updates
  - RGB LED and fan PWM control

**Key Commands (8-byte USB messages):**

| Cmd | Function | Description |
|-----|----------|-------------|
| 0 | Read waveform data | Reads RAM from triggered point, transmits via USB |
| 1 | Arm trigger | Sets trigger type, channel type, and capture length |
| 2 | Read status/registers | Returns version, board status, lock info, etc. |
| 3 | SPI transaction | Configures ADC chips via SPI |
| 4 | Set SPI mode | Selects SPI timing mode (0-3) |
| 5 | Reset PLLs | Resets clock generation PLLs |
| 6 | Adjust PLL phase | Fine-tunes clock phase for alignment |
| 7 | Switch clock source | Selects crystal oscillator or external clock |
| 8 | Set trigger thresholds | Programs trigger levels and options |
| 9 | Downsampling settings | Controls decimation rate and averaging |
| 10 | Control board outputs | Sets relay outputs, probe comp, etc. |
| 11 | RGB LED colors | Sets neo-pixel LED colors |
| 14 | Read register | Reads internal register value |
| 15 | Read flash | Reads byte from on-board flash memory |
| 16 | Write flash | Writes byte to flash (requires auth) |
| 17 | Erase flash | Bulk erases flash (requires auth) |

### 6. FTDI 245-FIFO Controller (ftdi245fifo/)
- **Purpose:** Interfaces with FT232H USB chip using 245-FIFO mode
- **Input:** 32-bit AXI-stream from command processor
- **Output:** 8-bit parallel data to FT232H chip
- **Features:** Handles USB flow control, data packing/unpacking, FIFOs for clock domain crossing
- **Third-party IP:** Based on open-source ftdi_245fifo_top module

### 7. Supporting Modules
- **SPI_Master.v:** Bit-banging SPI controller with configurable modes (0-3) and clock speed
- **phase_detector.v:** Measures time difference between signal edges using fast clock (for multi-board sync)
- **pwm_generator.v:** 8-bit PWM generator for fan speed control
- **neo_driver.v:** WS2812B protocol driver for RGB LED control
- **pll1-4.v:** Programmable clock generation and phase adjustment (Altera IP)

## Data Flow

### ADC Input → USB Output Pipeline

1. **ADC LVDS Input:** 4 ADC chips output 14-bit differential data at 800 Mbps
2. **LVDS Deserializer:** Converts serial LVDS to 140-bit parallel (10:1) at 100 MHz
3. **Downsampler:** Organizes 560 bits into 40 × 12-bit samples, applies decimation
4. **Triggerer:** Monitors samples for trigger conditions, controls RAM writes
5. **RAM Buffer:** Stores 1024 sets of 40 samples (circular buffer)
6. **Command Processor:** Receives USB commands, reads RAM from trigger point, reorders data
7. **FTDI Controller:** Converts 32-bit words to 8-bit USB, handles flow control
8. **USB to PC:** FT232H chip transmits data at USB 2.0 speeds (up to ~60-120 Mbps sustained)

### Data Width Conversions
- LVDS: 14 bits × 4 ADCs = 56 bits per LVDS bit time
- Deserialized: 56 bits × 10 = 560 bits per 100 MHz clock
- Samples: 40 × 12-bit = 480 bits of ADC data (+ 80 bits control/metadata)
- RAM: 560 bits × 1024 locations = 655 kB total
- USB: 32-bit words transmitted sequentially

## Clock Architecture

### Primary Clock Domains

1. **LVDS Clock (100 MHz)**
   - Derived from ADC sample clock via DPA
   - Feeds: Downsampler, Triggerer, RAM write port
   - Critical for timing accuracy

2. **Main Clock (50 MHz)**
   - Source: On-board crystal oscillator (switchable to external)
   - Feeds: Command processor, USB controller, control logic
   - Generated by PLL1 with multiple phase-adjustable outputs

3. **Flash/LED Clock (12.5 MHz)**
   - Divided from 50 MHz (÷4)
   - Feeds: Flash memory interface, RGB LED driver, PWM fan control

### Clock Domain Crossing (CDC)
- LVDS domain → 50 MHz domain: 2-3 stage synchronizer pipeline
- Synchronized signals: trigger state, RAM address, event counters, timestamps

## Triggering System

### Threshold Trigger Operation

The threshold trigger uses a **two-step detection** algorithm to prevent false triggers:

1. **Step 1:** Detect signal crossing threshold *outward*
   - Rising edge: sample < lower_threshold
   - Falling edge: sample > upper_threshold

2. **Step 2:** Detect signal crossing threshold *inward*
   - Rising edge: sample > upper_threshold
   - Falling edge: sample < lower_threshold
   - Also enforces Time-of-Threshold (ToT) holdoff

This hysteresis prevents noise from causing false triggers.

### Trigger Configuration
- **Thresholds:** Set via command 8, 12-bit signed values
- **Pre-trigger:** `prelengthtotake` samples captured before trigger
- **Post-trigger:** `lengthtotake` total samples after trigger fires
- **ToT:** Minimum time signal must remain outside thresholds
- **Holdoff:** Quiet time required between triggers

### Trigger Phase Detection
- Records which of 40 samples caused the trigger
- Provides sub-microsecond precision (~2.5 ns resolution)
- Enables precise trigger jitter elimination in post-processing

### Multi-Board Synchronization
- LVDS trigger outputs: `lvdsout_trig` (forward) and `lvdsout_trig_b` (backward echo)
- Supports daisy-chain topology with configurable "first"/"last" board designation
- Enables synchronized multi-channel capture across multiple Haasoscope Pro units
- Phase detector measures propagation delay for time correlation

## Advanced Features

### Pre-Trigger Capture
The firmware can capture samples *before* the trigger condition occurs by continuously writing to a circular RAM buffer. When a trigger fires, it records the current RAM address and the PC can read backwards to retrieve pre-trigger history.

### Rolling Trigger Mode
When armed but no trigger condition is met, the system automatically triggers periodically (~10 Hz) to allow observation of slow or repetitive signals without explicit triggering.

### Overrange Detection
Monitors 4 ADC overrange flags and counts saturation events, helping identify when signals exceed ADC input range.

### Event Time Stamping
A 32-bit counter increments at the LVDS clock rate and captures the timestamp when each trigger fires, enabling precise event correlation.

### Flash Firmware Updates
The firmware supports reading/writing the on-board flash memory, allowing firmware updates without a JTAG programmer (requires authentication to prevent accidental corruption).

### Fan Control & LED Indicators
- PWM-controlled cooling fan with software-adjustable duty cycle
- 2 RGB neo-pixel LEDs for status indication
- 10 board LEDs for debug output

## Key Files

| File | Purpose |
|------|---------|
| `command_processor.v` | Main control processor, USB interface, waveform readout |
| `triggerer.v` | Trigger state machine, RAM write control |
| `downsampler.v` | Sample organization, channel formatting, decimation |
| `rambuffer.v` | Dual-port RAM buffer wrapper |
| `SPI_Master.v` | SPI interface for ADC configuration |
| `phase_detector.v` | Multi-board trigger timing measurement |
| `pwm_generator.v` | Fan speed PWM control |
| `neo_driver.v` | RGB LED WS2812B protocol driver |
| `lvds1-4.v` | LVDS receiver and deserializer IP |
| `pll1-4.v` | Clock generation and phase adjustment IP |
| `ftdi245fifo/` | USB FTDI 245-FIFO interface modules |
| `coincidence.bdf` | Top-level block diagram schematic |
| `coincidence.qsf` | Quartus project settings file |

## Design Philosophy

The firmware architecture separates high-speed ADC data acquisition (100 MHz LVDS domain) from lower-speed control/USB operations (50 MHz domain) to maximize performance while maintaining flexibility. The circular RAM buffer and trigger system enable capture of fast transient events with pre-trigger history, while the USB interface allows full remote control and data retrieval. Multi-board synchronization via LVDS enables scaling to many channels while maintaining precise timing correlation.


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
 - In theory it should work out of the box, but you just need permissions to access it. Try this and then plug it in: <code>sudo cp blaster.rules /etc/udev/rules.d/</code>

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
