# calibration.py

import time
import numpy as np
from scipy.signal import resample


def find_rising_edges(x, y, threshold_percentile=20, min_slope_percentile=80):
    """
    Detect rising edges in a signal by finding points where the derivative exceeds a threshold.

    Args:
        x: Time values
        y: Signal values
        threshold_percentile: Percentile of signal range to use as minimum amplitude threshold
        min_slope_percentile: Percentile of derivative to use as minimum slope threshold

    Returns:
        Array of x positions (times) where rising edges occur
    """
    # Calculate derivative (rate of change)
    dy = np.diff(y)
    dx = np.diff(x)
    slope = dy / (dx + 1e-12)  # Avoid division by zero

    # Find threshold for what constitutes a "rising edge"
    y_range = np.max(y) - np.min(y)
    y_threshold = np.min(y) + y_range * (threshold_percentile / 100.0)
    slope_threshold = np.percentile(np.abs(slope), min_slope_percentile)

    # Find points where slope is positive and exceeds threshold, and signal is above minimum
    rising_mask = (slope > slope_threshold) & (y[:-1] > y_threshold)

    # Find the peaks (local maxima) in the derivative among rising regions
    edges = []
    i = 0
    while i < len(rising_mask):
        if rising_mask[i]:
            # Found start of rising region, find the peak slope in this region
            j = i
            while j < len(rising_mask) and rising_mask[j]:
                j += 1
            # Find index of maximum slope in this region
            peak_idx = i + np.argmax(slope[i:j])
            edges.append(x[peak_idx])
            i = j
        else:
            i += 1

    return np.array(edges)


def compute_edge_offset(edges1, edges2, max_offset):
    """
    Compute the time offset between two sets of edges by finding the shift that maximizes matches.

    Args:
        edges1: Array of edge times from first signal
        edges2: Array of edge times from second signal
        max_offset: Maximum offset to search (in same units as edge times)

    Returns:
        Optimal time offset (how much to shift signal 2 to align with signal 1)
    """
    if len(edges1) == 0 or len(edges2) == 0:
        print("Warning: No edges found in one or both signals")
        return 0

    # Search through possible offsets
    best_offset = 0
    best_score = -1

    # Use adaptive search range based on typical sample spacing
    search_resolution = max_offset / 1000.0
    offsets_to_try = np.arange(-max_offset, max_offset, search_resolution)

    for offset in offsets_to_try:
        # Shift edges2 by offset
        shifted_edges2 = edges2 + offset

        # Count how many edges match (are close to each other)
        matches = 0
        tolerance = search_resolution * 2  # Tolerance for "match"

        for e1 in edges1:
            distances = np.abs(shifted_edges2 - e1)
            if len(distances) > 0 and np.min(distances) < tolerance:
                matches += 1

        if matches > best_score:
            best_score = matches
            best_offset = offset

    print(f"Edge matching found {best_score} matched edges at offset {best_offset}")
    return best_offset


def autocalibration(main_window, resamp=2, dofiner=False, oldtoff=0, finewidth=16):
    """
    Performs an automated calibration to align the timing of two boards.
    It finds the coarse offset (Toff) and then the fine-grained offset (TAD).
    Uses rising edge detection for robust alignment.

    Args:
        main_window: Reference to the MainWindow instance
        resamp: Resampling factor for higher timing resolution
        dofiner: If True, performs fine-tuning phase
        oldtoff: Previous Toff value for fine-tuning
        finewidth: Width of search window for fine-tuning
    """
    # If called from the GUI, the first argument is 'False'. Reset to defaults.
    if not resamp:
        resamp = 2
        dofiner = False
        oldtoff = 0

    print(f"Autocalibration running with: resamp={resamp}, dofiner={dofiner}, finewidth={finewidth}")
    s = main_window.state

    if s.activeboard % 2 == 1:
        print("Error: Please select the even-numbered board of a pair (e.g., 0, 2) to calibrate.")
        return

    # Gently reset the fine-grained delay (TAD) to 0 before starting
    if s.tad[s.activeboard] != 0:
        print("Resetting TAD to 0 before calibration...")
        for t in range(abs(s.tad[s.activeboard]) // 5 + 1):
            current_tad = main_window.ui.tadBox.value()
            if current_tad == 0:
                break
            new_tad = current_tad - 5 if current_tad > 0 else current_tad + 5
            main_window.ui.tadBox.setValue(new_tad)  # This will trigger tad_changed
            time.sleep(.1)

    # Get data from the primary board and the board-under-test
    c1 = s.activeboard * s.num_chan_per_board
    c2 = (s.activeboard + 1) * s.num_chan_per_board
    c1data = main_window.xydata[c1]
    c2data = main_window.xydata[c2]

    # Resample data for higher timing resolution
    c1datanewy, c1datanewx = resample(c1data[1], len(c1data[0]) * resamp, t=c1data[0])
    c2datanewy, c2datanewx = resample(c2data[1], len(c2data[0]) * resamp, t=c2data[0])

    # Apply windowing around the vertical line (region of interest)
    fitwidth = (s.max_x - s.min_x) * s.fitwidthfraction
    vline = main_window.plot_manager.otherlines['vline'].value()

    window_mask1 = (c1datanewx > vline - fitwidth) & (c1datanewx < vline + fitwidth)
    window_mask2 = (c2datanewx > vline - fitwidth) & (c2datanewx < vline + fitwidth)

    x1_windowed = c1datanewx[window_mask1]
    y1_windowed = c1datanewy[window_mask1]
    x2_windowed = c2datanewx[window_mask2]
    y2_windowed = c2datanewy[window_mask2]

    # Find rising edges in both signals
    print("Detecting rising edges in both signals...")
    edges1 = find_rising_edges(x1_windowed, y1_windowed)
    edges2 = find_rising_edges(x2_windowed, y2_windowed)

    print(f"Found {len(edges1)} edges in signal 1, {len(edges2)} edges in signal 2")

    # Define the search range for the time shift
    if dofiner:
        max_time_offset = finewidth * (c1datanewx[1] - c1datanewx[0])
    else:
        max_time_offset = 10 * s.expect_samples * (c1datanewx[1] - c1datanewx[0])

    # Compute optimal offset using edge matching
    time_offset = compute_edge_offset(edges1, edges2, max_time_offset)

    # Convert time offset to sample shift
    sample_spacing = c1datanewx[1] - c1datanewx[0]
    minshift = int(round(time_offset / sample_spacing))

    print(f"Edge-based alignment found optimal shift = {minshift} samples ({time_offset} time units)")

    if dofiner:
        # Fine-tuning phase: adjust Toff slightly and set the final TAD value
        s.toff = minshift // resamp + oldtoff - 1
        main_window.ui.ToffBox.setValue(s.toff)

        # Convert the subsample shift into a hardware TAD value
        tadshift = round((138.4 * 2 / resamp) * (minshift % resamp), 1)
        tadshiftround = round(tadshift + 138.4)
        print(f"Optimal TAD value calculated to be ~{tadshiftround}")

        if tadshiftround < 250:
            print("Setting final TAD value...")
            for t in range(abs(s.tad[s.activeboard] - tadshiftround) // 5 + 1):
                current_tad = main_window.ui.tadBox.value()
                if abs(current_tad - tadshiftround) < 5:
                    break
                new_tad = current_tad + 5 if current_tad < tadshiftround else current_tad - 5
                main_window.ui.tadBox.setValue(new_tad)
                time.sleep(.1)
            print("Autocalibration finished.")
        else:
            print("Required TAD shift is too large. Adjusting clock phase and retrying.")
            main_window.controller.do_phase(s.activeboard + 1, plloutnum=0, updown=1, pllnum=0)
            main_window.controller.do_phase(s.activeboard + 1, plloutnum=1, updown=1, pllnum=0)
            main_window.controller.do_phase(s.activeboard + 1, plloutnum=2, updown=1, pllnum=0)
            s.triggerautocalibration[s.activeboard + 1] = True  # Request another calibration after new data
    else:
        # Coarse phase: find the rough Toff value, then do DC/RMS correction, then start the fine-tuning phase
        oldtoff = s.toff
        s.toff = minshift // resamp + s.toff
        print(f"Coarse Toff set to {s.toff}. Performing mean/RMS calibration...")
        do_meanrms_calibration(main_window)
        print("Starting fine-tuning phase...")
        autocalibration(main_window, resamp=64, dofiner=True, oldtoff=oldtoff)


def do_meanrms_calibration(main_window):
    """Calculates and applies DC offset and amplitude (RMS) corrections between two boards."""
    s = main_window.state

    for board_idx in range(s.num_board):
        if s.dooversample[board_idx] and board_idx % 2 == 0:

            # c1 is the primary board (e.g. board 0), c2 is the secondary (e.g. board 1)
            c1_idx = board_idx * s.num_chan_per_board
            c2_idx = (board_idx + 1) * s.num_chan_per_board

            # Get y-data for both channels within the fit window
            yc1 = main_window.xydata[c1_idx][1]
            yc2 = main_window.xydata[c2_idx][1]

            if len(yc1) < 10 or len(yc2) < 10:
                print("Mean/RMS calibration failed: not enough data in window.")
                return

            # Calculate mean and standard deviation for each channel
            mean_primary = np.mean(yc1)
            #print(mean_primary)
            std_primary = np.std(yc1)
            #print(std_primary)
            mean_secondary = np.mean(yc2)
            #print(mean_secondary)
            std_secondary = np.std(yc2)
            #print(std_secondary)

            # The correction to ADD to the secondary data is (primary - secondary)
            mean_cor = mean_primary - mean_secondary
            if abs(mean_cor)<1:
                s.extrigboardmeancorrection[s.activeboard] += mean_cor

            # The correction to MULTIPLY the secondary data by is (primary / secondary)
            if std_primary > 0 and std_secondary > 0:
                std_corr = std_primary / std_secondary
                if std_corr<1.5:
                    s.extrigboardstdcorrection[s.activeboard] *= std_corr

            print(f"Updated corrections to be applied to board {s.activeboard + 1}: "
                  f"Mean+={s.extrigboardmeancorrection[s.activeboard]:.4f}, "
                  f"Std*={s.extrigboardstdcorrection[s.activeboard]:.4f}")
