# data_recorder.py

import time
import os


class DataRecorder:
    def __init__(self, state):
        self.state = state
        self.is_recording = False
        self.file_handle = None
        self.event_count = 0
        self.event_count_max = 1000
        self.file_part = 0
        self.base_filename = ""
        self.record_dir = None

    def start(self):
        """Opens a new file for recording with a timestamp in its name."""
        if self.is_recording:
            print("Already recording.")
            return False

        # If this is the very first file, create a base timestamped name
        if self.file_part == 0:
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            base = f"HaasoscopePro_data_{timestamp}"
            if self.record_dir:
                self.base_filename = os.path.join(self.record_dir, base)
            else:
                self.base_filename = base

        self.file_part += 1
        self.event_count = 0

        try:
            filename = f"{self.base_filename}_part_{self.file_part}.csv"
            self.file_handle = open(filename, 'w')
            self.is_recording = True
            print(f"Recording started to {filename}")
            return True
        except IOError:
            self.is_recording = False
            return False

    def stop(self, reset=True):
        """Closes the recording file if it's open."""
        if self.is_recording and self.file_handle:
            self.file_handle.close()
            #print(f"Recording stopped. File {self.file_handle.name} closed.")
        self.file_handle = None
        self.is_recording = False
        # Reset file part counter when recording is manually stopped
        if reset: self.file_part = 0

    def record_event(self, xydata, vline_val, visible_lines):
        """
        Writes the data for the current event to the file in a CSV-like format.
        Format: vline_pos, x0, y0, x1, y1, ..., xN, yN, on/off_ch1, on/off_ch2, ...
        """
        if not self.is_recording or self.file_handle is None:
            return

        # Check if we need to roll over to a new file
        if self.event_count >= self.event_count_max:
            self.stop(reset=False)
            self.start()  # This will open the next part
            # After start(), self.is_recording will be True again if successful

        s = self.state
        num_channels = s.num_board * s.num_chan_per_board
        line_parts = [str(vline_val)]

        for i in range(num_channels):
            # Two-channel mode is a per-board setting, so resolve it for the board this channel is on.
            board_idx = i // s.num_chan_per_board
            if s.dotwochannel[board_idx]:
                # In two-channel mode each channel is sampled at half the rate (1.6 GS/s instead of 3.2 GS/s),
                # so only the first half of the array holds valid samples (the rest is stale), and those
                # samples are spaced twice as far apart in time. The stored x-axis always uses the
                # single-channel spacing (with trigger-stabilizer corrections applied in that same scale),
                # so multiply by 2 to get the true sample times - exactly as plot_manager does for display.
                num_samples = xydata.shape[2] // 2
                x_data = xydata[i][0][:num_samples] * 2.0
            else:
                num_samples = xydata.shape[2]
                x_data = xydata[i][0][:num_samples]
            y_data = xydata[i][1][:num_samples]

            for x, y in zip(x_data, y_data):
                line_parts.append(f"{x:.4f}")
                line_parts.append(f"{y:.4f}")

        # Append visibility status for each line
        for is_visible in visible_lines:
            if is_visible:
                line_parts.append("on")
            else:
                line_parts.append("off")

        self.file_handle.write(','.join(line_parts) + '\n')
        self.event_count += 1
