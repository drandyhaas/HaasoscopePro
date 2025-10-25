# Dummy Oscilloscope Server

A TCP socket-based simulator for testing HaasoscopePro software without physical hardware.

## Overview

The dummy server (`dummy_server.py`) simulates a HaasoscopePro oscilloscope board by implementing the same command protocol over TCP sockets. It generates realistic waveforms (sine, square, pulse) and responds to all standard oscilloscope commands, allowing you to develop and test HaasoscopePro software features without requiring physical hardware.

## Components

- **`dummy_server.py`** - Main TCP server that simulates oscilloscope board behavior
- **`USB_Socket.py`** - Socket adapter implementing USB-compatible interface for seamless integration
- **`dummy_server_config_dialog.py`** - GUI dialog for real-time waveform configuration
- **`__init__.py`** - Package initialization

## Why Use the Dummy Server?

- **Software Development** - Test new features without hardware
- **Debugging** - Reproduce specific signal conditions reliably
- **CI/CD Testing** - Automated testing in continuous integration pipelines
- **Training** - Learn HaasoscopePro software without risking hardware
- **Multi-Board Testing** - Simulate multiple boards simultaneously by running multiple servers

## Quick Start

### 1. Start the Dummy Server

```bash
cd software/dummy_scope
python dummy_server.py --port 9999
```

The server will start listening on `localhost:9999` and display:
```
Opening port 9999
Dummy oscilloscope server running on localhost:9999
Press Ctrl+C to stop
```

### 2. Connect HaasoscopePro Software

Launch the main application with the `--socket` parameter:

```bash
cd software
python HaasoscopeProQt.py --socket localhost:9999
```

The software will connect to the dummy server instead of looking for USB hardware.

**Note:** The `--socket` argument can be specified multiple times for multi-board simulation (see below).

## Command Line Options

```bash
python dummy_server.py [OPTIONS]
```

**Options:**
- `--host HOST` - Bind address (default: `localhost`)
- `--port PORT` - TCP port number (default: `9998`)
- `--firmware VERSION` - Firmware version to report (default: `0`)
- `--no-noise` - Disable noise for deterministic outputs (useful for automated testing)

**Examples:**
```bash
# Start on default port 9998
python dummy_server.py

# Start on port 9999
python dummy_server.py --port 9999

# Listen on all interfaces (allows remote connections)
python dummy_server.py --host 0.0.0.0 --port 9999

# Simulate firmware version 31
python dummy_server.py --firmware 31

# Run in deterministic mode (no noise, fixed phase) for testing
python dummy_server.py --no-noise --port 9999
```

## Waveform Configuration

### Default Waveforms

**Channel 0** (default):
- Type: Sine wave
- Frequency: 3.2 MHz
- Amplitude: 1500 ADC counts

**Channel 1** (default):
- Type: Pulse
- Frequency: 100 MHz
- Pulse rise time: 8 samples
- Pulse decay time: 40 samples
- Amplitude: 10-500 ADC counts (randomized per pulse)

### Runtime Configuration

Use the GUI configuration dialog in HaasoscopePro:
1. Launch HaasoscopePro connected to dummy server
2. Open **Tools** → **Dummy Server Config** menu
3. Select channel and waveform type
4. Adjust parameters in real-time

**Available Waveform Types:**

**Sine Wave**
- Frequency (Hz)
- Amplitude (ADC counts)

**Square Wave**
- Frequency (Hz)
- Amplitude (ADC counts)
- Rise/Fall sharpness (1-100, higher = sharper edges)

**Pulse**
- Frequency (Hz)
- Rise time constant (samples)
- Decay time constant (samples)
- Minimum amplitude (ADC counts)
- Maximum amplitude (ADC counts)

### Configuration Protocol

Waveform settings can be changed via opcode **128** (custom configuration command):

```python
# Command format: [128, channel, param_id, value_bytes...]
# See dummy_server.py for parameter IDs
```

## Simulated Features

The dummy server accurately simulates:

### Hardware State
- ✓ Firmware version reporting
- ✓ PLL lock status
- ✓ Temperature sensors (ADC and board)
- ✓ Fan control (PWM)
- ✓ External clock detection
- ✓ Board position (first/middle/last)

### Trigger System
- ✓ Rising/falling edge triggering
- ✓ Trigger level and hysteresis (delta)
- ✓ Trigger position in waveform
- ✓ Trigger counter
- ✓ Phase-coherent triggering (waveform aligns to trigger point)

### Channel Configuration
- ✓ Single/dual channel modes
- ✓ Per-channel gain (dB)
- ✓ Per-channel offset
- ✓ AC/DC coupling
- ✓ 50Ω / 1MΩ impedance
- ✓ Attenuator settings

### Data Acquisition
- ✓ Downsampling (decimation and averaging modes)
- ✓ Sample merging
- ✓ Continuous waveform generation
- ✓ Noise simulation (1% RMS by default, disable with `--no-noise` for deterministic testing)

### Advanced Features
- ✓ SPI mode switching
- ✓ Aux output control
- ✓ Clock splitter for oversampling mode
- ✓ Status register bits

## Deterministic Mode for Testing

When running automated tests, you can use the `--no-noise` flag to ensure completely reproducible outputs:

```bash
python dummy_server.py --no-noise --port 9999
```

**In deterministic mode:**
- ✓ No random noise added to waveforms (clean signals)
- ✓ Fixed starting phase (always 0.0 radians)
- ✓ Pulse amplitudes use average of min/max range (no randomization)
- ✓ Pulse positions are fixed (no jitter)
- ✓ Identical waveforms generated for identical settings

**Use cases:**
- **Screenshot comparison tests** - Pixel-perfect comparison of UI output
- **Data validation tests** - Verify processing algorithms with known inputs
- **Regression testing** - Detect changes in signal processing behavior
- **CI/CD pipelines** - Reproducible test results across different runs

**Example test workflow:**
```bash
# Start deterministic dummy server
python dummy_server.py --no-noise --port 9999 &

# Run automated tests
python test/test_gui_automated.py --socket localhost:9999

# All screenshots and data will be identical across runs
```

## Technical Details

### Protocol Compatibility

The dummy server implements the complete HaasoscopePro command protocol:

| Opcode | Function | Status |
|--------|----------|--------|
| 0 | Reset | ✓ |
| 1 | Set mode (trigger type, channels) | ✓ |
| 2 | Temperature request | ✓ |
| 3 | Analog controls | ✓ |
| 5 | Return status | ✓ |
| 8 | Set trigger parameters | ✓ |
| 9 | Set downsample | ✓ |
| 10-13 | SPI commands | ✓ |
| 14 | Board position | ✓ |
| 15-19 | PLL/clock control | ✓ |
| 22 | Fan control | ✓ |
| 128 | Waveform config (custom) | ✓ |

### Data Format

Waveform data is returned as 16-bit signed integers (ADC counts):
- 12-bit ADC resolution (values: 0-4095)
- Packed into upper 12 bits of 16-bit word
- Single channel: 3.2 GS/s effective
- Dual channel: 1.6 GS/s per channel

### Phase Continuity

The server maintains phase continuity across acquisitions using a `data_counter` that increments continuously, ensuring realistic signal behavior when viewing persistent or rolling displays.

### Trigger Alignment

When trigger parameters are set (opcode 8), the server:
1. Parses trigger level, position, and delta
2. Generates waveform with threshold crossing at requested position
3. Uses `arcsin` calculation to determine starting phase
4. Reports detected trigger position back to software

This creates realistic trigger-synchronized waveforms.

## Multi-Board Simulation

Run multiple dummy servers on different ports to simulate multi-board setups:

```bash
# Terminal 1 - Board 0
python dummy_server.py --port 9998

# Terminal 2 - Board 1
python dummy_server.py --port 9999

# Terminal 3 - Board 2
python dummy_server.py --port 10000
```

Then connect (specify `--socket` multiple times):
```bash
python HaasoscopeProQt.py --socket localhost:9998 --socket localhost:9999 --socket localhost:10000
```

You can also mix hardware and dummy boards - if physical boards are detected, socket boards are added to the list.

## Troubleshooting

**Connection refused**
- Ensure dummy server is running before launching HaasoscopePro
- Check firewall settings if using remote host
- Verify port number matches between server and client

**No waveform displayed**
- Check that trigger settings are appropriate for the signal
- Try "Auto" trigger mode
- Verify channel is enabled in the UI

**Waveform looks wrong**
- Check waveform configuration via config dialog
- Verify gain/offset settings
- Check downsample settings

**Configuration changes not applying**
- Ensure only one client is connected
- Check server console for error messages
- Restart server and reconnect client

## Development Notes

### Adding New Waveform Types

Edit `dummy_server.py` and add to `_generate_waveform()`:

```python
elif wave_type == "my_waveform":
    # Your waveform generation code
    waveform = ...
    return waveform
```

Then add UI controls in `dummy_server_config_dialog.py`.

### Adding New Commands

Implement new opcode handlers in `_handle_opcode()`:

```python
elif opcode == YOUR_NEW_OPCODE:
    # Parse data
    # Update board_state
    # Return response bytes
    return response
```

### Debugging

Enable verbose logging by modifying the server:

```python
# Add at start of _handle_opcode()
print(f"Opcode {opcode}: {data.hex()}")
```

## Performance

- **Latency**: ~1-5ms per command (local connection)
- **Data Rate**: Up to 100 MB/s transfer rate
- **CPU Usage**: ~5-10% per server instance
- **Memory**: ~50 MB per server

## License

Same as parent HaasoscopePro project (open source).

## See Also

- [Main HaasoscopePro README](../../README.md)
- [HaasoscopePro User Guide](https://hackaday.io/project/200773-haasoscope-pro)
- [FTDI Driver Setup](../ftdi_setup.exe)
