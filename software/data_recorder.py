# data_recorder.py

import time


class DataRecorder:
    def __init__(self, state):
        self.state = state
        self.is_recording = False
        self.file_handle = None
        self.event_count = 0
        self.event_count_max = 1000
        self.file_part = 0
        self.base_filename = ""

    def start(self):
        """Opens a new file for recording with a timestamp in its name."""
        if self.is_recording:
            print("Already recording.")
            return False

        # If this is the very first file, create a base timestamped name
        if self.file_part == 0:
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            self.base_filename = f"HaasoscopePro_data_{timestamp}"

        self.file_part += 1
        self.event_count = 0

        try:
            filename = f"{self.base_filename}_part_{self.file_part}.csv"
            self.file_handle = open(filename, 'w')
            self.is_recording = True
            #print(f"Recording started to {filename}")
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

        # Determine the number of valid samples based on the mode of the first board
        # This is a simplification; assumes all boards are in the same mode.
        board_idx = 0
        if s.dotwochannel[board_idx]:
            num_samples = self.state.expect_samples * 20  # xydata.shape[2] // 2
        else:
            num_samples = self.state.expect_samples * 40  # xydata.shape[2]

        for i in range(num_channels):
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
