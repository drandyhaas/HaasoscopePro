# calibration.py

import time, math
import numpy as np
from scipy.signal import resample
from data_processor import find_crossing_distance


def reset_TAD(main_window):
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

def autocalibration(main_window):
    """
    Performs an automated calibration to align the timing of two boards.
    """

    s = main_window.state
    if s.activeboard % 2 == 1:
        print("Error: Please select the even-numbered board of a pair (e.g., 0, 2) to calibrate.")
        return

    # Get data from the primary board and the board-under-test
    c1 = s.activeboard * s.num_chan_per_board
    c2 = (s.activeboard + 1) * s.num_chan_per_board
    c1data = main_window.xydata[c1]
    c2data = main_window.xydata[c2]
    y1 = c1data[1]
    y2 = c2data[1]
    sample_spacing = c1data[0][1] - c1data[0][0]

    vline = main_window.plot_manager.otherlines['vline'].value()
    hline = main_window.plot_manager.otherlines['hline'].value()
    edge1 = find_crossing_distance(y1,hline,vline, 0, sample_spacing)
    edge2 = find_crossing_distance(y2,hline,vline, 0, sample_spacing)
    print(f"Found {edge1} in signal 1, {edge2} in signal 2")

    # make sure c2 is left of c1 by at least half a sample, so we can use TAD to get it right to half a sample difference
    time_offset = edge1-edge2 - (sample_spacing) # /2.0 ???
    sample_offset = math.floor(time_offset / sample_spacing)

    print(f"Edge-based alignment found {time_offset} ns shift, and {sample_offset} nearest samples")
    s.toff += sample_offset
    main_window.ui.ToffBox.setValue(s.toff) # TODO: should be per oversampling pair of boards

    # Convert the subsample shift into a hardware TAD value
    remaining_time_offset = time_offset - sample_offset*sample_spacing
    print("remaining_time_offset", remaining_time_offset)
    tadshift = remaining_time_offset * 138.4 / (sample_spacing/2.0)
    print("tadshift",tadshift)
    tadshiftround = round(tadshift)
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
        print("Required TAD shift is too large. Adjusting clock. Re-run autocalibration!") # TODO: rerun automatically
        main_window.controller.do_phase(s.activeboard + 1, plloutnum=0, updown=1, pllnum=0)
        main_window.controller.do_phase(s.activeboard + 1, plloutnum=1, updown=1, pllnum=0)
        main_window.controller.do_phase(s.activeboard + 1, plloutnum=2, updown=1, pllnum=0)


def do_meanrms_calibration(main_window, doprint=False):
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

            if doprint:
                print(f"Updated corrections to be applied to board {s.activeboard + 1}: "
                      f"Mean+={s.extrigboardmeancorrection[s.activeboard]:.4f}, "
                      f"Std*={s.extrigboardstdcorrection[s.activeboard]:.4f}")
