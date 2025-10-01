# calibration.py

import time
import numpy as np
from scipy.signal import resample


def autocalibration(main_window, resamp=2, dofiner=False, oldtoff=0, finewidth=16):
    """
    Performs an automated calibration to align the timing of two boards.
    It finds the coarse offset (Toff) and then the fine-grained offset (TAD).
    
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

    # Define the search range for the time shift
    minrange = -s.toff * resamp
    if dofiner:
        minrange = (s.toff - oldtoff - finewidth) * resamp
    maxrange = 10 * s.expect_samples * resamp
    if dofiner:
        maxrange = (s.toff - oldtoff + finewidth) * resamp

    c2datanewy = np.roll(c2datanewy, int(minrange))

    minrms = 1e9
    minshift = 0
    fitwidth = (s.max_x - s.min_x) * s.fitwidthfraction
    vline = main_window.plot_manager.otherlines['vline'].value()

    # Iterate through all possible shifts and find the one with the minimum RMS difference
    print(f"Searching for best shift in range {minrange} to {maxrange}...")
    for nshift in range(int(minrange), int(maxrange)):
        yc1 = c1datanewy[(c1datanewx > vline - fitwidth) & (c1datanewx < vline + fitwidth)]
        yc2 = c2datanewy[(c2datanewx > vline - fitwidth) & (c2datanewx < vline + fitwidth)]
        if len(yc1) != len(yc2):
            continue  # Skip if windowing results in unequal lengths

        therms = np.std(yc1 - yc2)
        if therms < minrms:
            minrms = therms
            minshift = nshift
        c2datanewy = np.roll(c2datanewy, 1)

    print(f"Minimum RMS difference found for total shift = {minshift}")

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
