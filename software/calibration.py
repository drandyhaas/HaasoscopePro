# calibration.py

import time, math
import numpy as np
from data_processor import find_crossing_distance


class AutocalibrationCollector:
    """Collects data over multiple events for autocalibration."""

    def __init__(self, main_window, num_events):
        self.main_window = main_window
        self.num_events = num_events
        self.timeshifts = []
        self.s = main_window.state
        self.c1 = self.s.activeboard * self.s.num_chan_per_board
        self.c2 = (self.s.activeboard + 1) * self.s.num_chan_per_board
        self.events_collected = -1
        self.sample_spacing = 1.0
        self.TAD_PER_HALF_SAMPLE = 1.0 # to change unit from TAD to time (ns)
        self.was_drawing = None

    def collect_event_data(self):
        """Called by update_plot_loop to collect data from the current event."""
        # Get data from the current event
        c1data = self.main_window.xydata[self.c1]
        c2data = self.main_window.xydata[self.c2]
        y1 = c1data[1]
        y2 = c2data[1]
        self.sample_spacing = c1data[0][1] - c1data[0][0]
        self.TAD_PER_HALF_SAMPLE = 138.4 / (self.sample_spacing / 2.0)

        vline = self.main_window.plot_manager.otherlines['vline'].value()
        hline = self.main_window.plot_manager.otherlines['hline'].value()
        edge1 = find_crossing_distance(y1, hline, vline, 0, self.sample_spacing)
        edge2 = find_crossing_distance(y2, hline, vline, 0, self.sample_spacing)

        self.events_collected += 1
        if self.events_collected == 0:
            #print(f"Event 1: Found {edge1:.2f} in signal 1, {edge2:.2f} in signal 2")
            return False # skip the first event, since phases or other things may have changed

        # Calculate offsets for this event
        timeshift = edge1 - edge2 - (self.sample_spacing/2.0) + self.s.tad[self.s.activeboard]/self.TAD_PER_HALF_SAMPLE
        self.timeshifts.append(timeshift)

        if self.events_collected % 20 == 0:
            print(f"  Processed {self.events_collected}/{self.num_events} events for oversampling calibration...")

        # Return True if we've collected enough events
        return self.events_collected >= self.num_events

    def apply_calibration(self):
        """Apply the averaged calibration after collecting all events."""
        if self.events_collected == 0:
            print("Error: No valid events collected for calibration?!")
            return

        # Calculate average time offset
        time_offset = np.mean(self.timeshifts)

        # find sample offset
        sample_offset = math.floor(time_offset / self.sample_spacing)

        # Calculate TAD shift for this event
        remaining_time_offset = time_offset - sample_offset * self.sample_spacing
        tadshift = remaining_time_offset * self.TAD_PER_HALF_SAMPLE
        tadshiftround = round(tadshift)

        print(f"  Averaging complete:")
        #print(f"  Got {self.events_collected} events")
        print(f"  Samples delay: {sample_offset}")
        print(f"  TAD shift: {tadshift:.2f} +- {self.TAD_PER_HALF_SAMPLE*np.std(self.timeshifts)/math.sqrt(self.events_collected):.2f}")
        print(f"  Old TAD was: {self.s.tad[self.s.activeboard]}")
        #print(f"  Fine delay: {tadshiftround}")

        # Apply the averaged corrections
        self.s.toff += sample_offset
        self.main_window.ui.ToffBox.setValue(self.s.toff)
        if tadshiftround > 255:
            print("Required TAD shift is too large. Adjusting PLL a step down on other board.")
            self.main_window.controller.do_phase(self.s.activeboard + 1, plloutnum=0, updown=0, pllnum=0)
            self.main_window.controller.do_phase(self.s.activeboard + 1, plloutnum=1, updown=0, pllnum=0)
            self.main_window.controller.do_phase(self.s.activeboard + 1, plloutnum=2, updown=0, pllnum=0)
            self.s.extraphasefortad[self.s.activeboard + 1] = 1
            print("Asking for re-run of calibration.")
            self.s.triggerautocalibration[self.s.activeboard] = True
        else:
            print("Setting final fine delay:", tadshiftround)
            for t in range(abs(self.s.tad[self.s.activeboard] - tadshiftround) + 5):
                current_tad = self.main_window.ui.tadBox.value()
                if abs(current_tad - tadshiftround) < 1:
                    break
                new_tad = current_tad + 1 if current_tad < tadshiftround else current_tad - 1
                self.main_window.ui.tadBox.setValue(new_tad)
                time.sleep(.01)
            print("Autocalibration finished.")


def autocalibration(main_window, num_events=100):
    """
    Initiates automated calibration to align the timing of two boards.
    Averages over multiple events to reduce event-to-event fluctuations.

    Args:
        main_window: The main window object
        num_events: Number of events to average over (default: 100)
    """
    s = main_window.state
    if s.activeboard % 2 == 1 or not s.dooversample[s.activeboard]:
        print("Error: Please select the even-numbered board of an oversampling pair (e.g., 0, 2) to calibrate.")
        return

    print(f"Starting autocalibration: averaging over {num_events} events...")
    # Create a collector and register it with the main window
    main_window.autocalib_collector = AutocalibrationCollector(main_window, num_events)


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
            s.extrigboardmeancorrection[s.activeboard] += max(min(mean_cor,1),-1) # cap the correction just in case

            # The correction to MULTIPLY the secondary data by is (primary / secondary)
            if std_primary > 0 and std_secondary > 0:
                std_corr = std_primary / std_secondary
                s.extrigboardstdcorrection[s.activeboard] *= max(min(std_corr,2),0.5) #  cap the correction just in case

            if doprint:
                print(f"Updated corrections to be applied to board {s.activeboard + 1}: "
                      f"Mean+={s.extrigboardmeancorrection[s.activeboard]:.4f}, "
                      f"Std*={s.extrigboardstdcorrection[s.activeboard]:.4f}")
