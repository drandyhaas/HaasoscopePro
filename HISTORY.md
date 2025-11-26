# The Development History of the Haasoscope Pro

## A Historical Essay on the Evolution of an Open-Source High-Speed Oscilloscope

### Origins: July 2024

The Haasoscope Pro project began on July 25, 2024, with an initial commit that would mark the start of an ambitious endeavor: creating a high-performance, multi-gigasample oscilloscope from the ground up. The project was primarily developed by Andy Haas (with later contributions from Dmitri Priimak), building on experience from earlier Haasoscope projects.

The very first days focused on establishing USB communication using the FT232H chip from FTDI. By July 26, the foundational work was underway—implementing FIFO buffers and achieving working loopback communication. The commit message "ft232h working loopback and mass sending" marked the first successful data transfer milestone.

### Phase I: Foundation and ADC Bring-up (July-August 2024)

The initial architecture took shape rapidly. By July 28, a command processor was operational, capable of sending back version information and clock switching data. SPI communication was implemented the same day, essential for configuring the ADC and other peripherals.

July 29 saw the introduction of LVDS (Low-Voltage Differential Signaling), the high-speed interface that would connect the ADC to the FPGA. The pin assignments for a 14-channel LVDS input (including clock and strobe) were mapped to the ADC board.

The first analog success came on July 31: "analog input B works at 500 MHz." This was a pivotal moment—the system could now digitize real signals at high speed.

August 1-2 brought working FIFO implementation with stability improvements. The commit "Working analog - turn on 1.1V _before_ 1.9V" reveals the careful attention to power sequencing required for high-speed ADCs. By August 2, LVDS was running at 400 MHz with proper timing closure.

August 6 marked the birth of the Qt-based graphical user interface: "initial port of Qt display" followed by "Qt display running with sample data, and can shift clock phase." The ability to visualize waveforms and adjust clock phase interactively was crucial for debugging the high-speed data path.

### Phase II: Pushing Performance Boundaries (August-September 2024)

The sample rate climbed rapidly through August 2024:
- **600 MHz** (August 12): "600 MHz sample rate (LVDS at 300 MHz, lvdsclk at 150 MHz)"
- **800 MHz** (August 14): "LVDS at 800 MHz (lvdsclk at 400, and clk at 1600)"
- **1.4 GHz** (August 31): "1400 MHz (700 Mbps per lvds link) (2.8 Gsps single-channel)"
- **2.9 GHz** (September 11): "2.9 GHz again"
- **3.2 Gsps** (September 17): "3.2 Gsps, spimode needed"

The hardware evolved in parallel. The first board revision (v1.10/v1.11) was ordered on August 18. Sub-boards were developed separately:
- **Power board** (v1.11): USB-C power delivery with +0.1V adjustment options
- **Input board** (v1.1): DAC offset control
- **Clock board**: ADF4350-based synthesizer for precise frequency generation

August 13 introduced the rudimentary trigger system with low/high thresholds—a fundamental oscilloscope feature. Trigger types were expanded throughout August, with rising edge and pattern-based triggering added.

### Phase III: The Integrated Design (September-October 2024)

September and October 2024 saw the consolidation from prototype boards into a unified design. The "full board" development started September 30, combining all sub-boards onto a single PCB. The routing process was documented through numerous commits:
- "add all other boards" (October 1)
- "placed everything but power board" (October 2)
- "fully routed" (October 4)
- "v1.00" (October 7)

The firmware underwent significant architectural changes. October 8 brought a crucial improvement: "Use dual-port RAM buffer instead of FIFO"—enabling more sophisticated trigger position control and memory management.

October saw the implementation of many essential oscilloscope features:
- **Trigger position control** (October 9)
- **Rising edge trigger** (October 9)
- **Adjustable gain** (October 9)
- **Time over Threshold (ToT) trigger** (October 10)
- **Downsampling** (October 11-12): Supporting factors of 2, 4, 8, 20, and 40

### Phase IV: Multi-Board Support (October-November 2024)

A major architectural expansion came in late October: multi-board synchronization. The commits "Open list of USBs" and "Use multiple usb devices" (October 29) enabled connecting multiple Haasoscope Pro units together.

External triggering between boards was implemented November 1: "ext trig synced." This capability allowed synchronized acquisition across multiple units, effectively multiplying channel count.

The board design continued refinement through version 1.10 (November 1), with careful attention to signal integrity, thermal management, and manufacturing constraints.

### Phase V: Software Maturation (January-April 2025)

The new year brought extensive software improvements. January 2025 introduced:
- **FFT plot** (January 2)
- **Neopixel LED control** (January 2)
- **Dynamic two-channel mode** (January 3-12)
- **Volts per division** display (January 7)
- **Rolling/auto trigger** modes (January 23)

February and March focused on stability, documentation, and community contributions. Dmitri Priimak began contributing code cleanup and new features through pull requests:
- Force arm trigger functionality
- Register read functions
- Code style improvements

April 2025 brought flash programming capabilities, allowing firmware updates without a JTAG programmer. The data processing was optimized significantly: "Add direct processing of data using arrays... Getting about 75 Hz on my Windows desktop with no drawing and 1000 mem-depth, about 8 MB/s" (April 12).

### Phase VI: External Interfaces and Protocol Support (May-June 2025)

May 2025 introduced SCPI (Standard Commands for Programmable Instruments) socket support, enabling integration with external software like ngscopeclient. This opened the Haasoscope Pro to the broader test and measurement ecosystem.

Multi-board synchronization was refined with LVDS trigger echo timing, allowing precise delay measurement and compensation between boards.

### Phase VII: The Great Refactoring (September-October 2025)

September 2025 marked a significant software reorganization. The monolithic codebase was split into modular components:
- `fft_window.py`: FFT analysis
- `scpi_socket.py`: Network protocol handling
- `spi.py`: Hardware communication
- `board.py`: Board abstraction
- `measurements.py`: Signal measurements

This refactoring, culminating in version 29, made the code more maintainable and enabled rapid feature development.

New features appeared rapidly:
- **Persistence display with heatmap** (October 26)
- **Math channels** with operations like addition, subtraction, FFT (October 5)
- **Cursor measurements** (October 5)
- **Reference waveforms** (September 28)
- **Histogram measurements** (September 30)
- **Peak detection** (October 9)
- **FIR filters** for signal correction (October-November)

### Phase VIII: Runt Trigger and Advanced Features (November 2025)

Firmware version 32 (November 3, 2025) added runt trigger capability—detecting pulses that cross one threshold but not another. This specialized trigger mode is essential for catching signal integrity problems.

The LVDS calibration system was enhanced for multi-board setups, automatically measuring and correcting timing delays between boards.

The most recent developments include:
- **USB3 support** for increased data transfer bandwidth (November 25-26, 2025)
- Per-board FIR filter calibration
- Keyboard shortcuts for efficient operation

---

## Hardware Architecture

The Haasoscope Pro hardware consists of several integrated components:

### ADC Board
Features the ADC12DL2500, a dual-channel 12-bit ADC capable of 2.5 Gsps per channel or 5 Gsps interleaved. The ADC connects to the FPGA via 14 LVDS pairs.

### FPGA
An Intel (Altera) Cyclone IV EP4CE30F23C6N processes the incoming data, implements triggering logic, and manages data transfer to the host.

### Clock System
ADF4350 synthesizer generates the sample clock, locked to a 50 MHz reference. The system supports external clock input for multi-board synchronization.

### Input Conditioning
Relay-switched attenuation, AC/DC coupling, and 50Ω/1MΩ input impedance selection.

### USB Interface
FT232H provides high-speed USB 2.0 communication. USB3 support is under development for higher bandwidth.

---

## Firmware Evolution

The FPGA firmware progressed through 32+ versions, each adding capabilities:

| Version Range | Key Features |
|---------------|--------------|
| v1-v10 | Basic ADC interfacing and data transfer |
| v11-v20 | Trigger improvements, downsampling, multi-board support |
| v21-v25 | Flash programming, phase calibration |
| v26-v30 | Trigger stability, timing refinement |
| v31-v32 | FIR correction, runt trigger, LVDS calibration improvements |

### Key Firmware Modules

- `command_processor.v`: USB command handling
- `triggerer.v`: Trigger detection logic (~26K lines)
- `downsampler.v`: Sample rate reduction with averaging
- `rambuffer.v`: Dual-port acquisition memory
- `SPI_Master.v`: Peripheral communication

---

## Software Stack

The Python-based software evolved from a simple Qt display into a full-featured oscilloscope application:

### Technologies
- **PyQt5** for the GUI
- **pyqtgraph** for real-time waveform display
- **NumPy** for signal processing
- **SciPy** for curve fitting and filtering

### Capabilities
- Up to 8+ synchronized boards
- Real-time FFT analysis
- Math channels with arbitrary operations
- Persistence display with heatmap
- SCPI remote control
- Settings save/load
- Screenshot capture

---

## Contributors

The project was primarily developed by **Andy Haas**, with over 1,700 commits spanning 16 months. **Dmitri Priimak** contributed code cleanup, the force-arm trigger feature, and various improvements through pull requests beginning in March 2025.

---

## Conclusion

The Haasoscope Pro represents a remarkable open-source achievement: a 3.2 Gsps oscilloscope developed from initial concept to production-ready design in approximately 16 months. The git history reveals the iterative nature of hardware/firmware/software co-development, with continuous refinement driven by real-world testing.

From the first "ft232h working loopback" message to the latest USB3 enhancements, the project demonstrates how modern open-source tools, affordable FPGAs, and high-speed ADCs enable individual developers to create instruments that rival commercial offerings at a fraction of the cost.

The development continues, with USB3 support, advanced trigger modes, and improved calibration expanding the capabilities of this remarkable instrument.

---

*This essay was compiled from analysis of 1,730 git commits spanning July 25, 2024 to November 26, 2025.*
