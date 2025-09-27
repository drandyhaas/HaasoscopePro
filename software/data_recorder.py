# data_recorder.py

import time
import numpy as np


class DataRecorder:
    def __init__(self, state):
        self.state = state
        self.is_recording = False
        self.file_handle = None

    def start(self):
        if self.is_recording: return
        fname = "HaasoscopePro_out_" + time.strftime("%Y%m%d-%H%M%S") + ".csv"
        try:
            self.file_handle = open(fname, "wt")
            header = "Event #, Time (s), Channel, Trigger time (ns), Sample period (ns), # samples"
            num_samples = 4 * 10 * self.state.expect_samples
            sample_headers = "".join([f", Sample {s}" for s in range(num_samples)])
            self.file_handle.write(header + sample_headers + "\n")
            self.is_recording = True
            print(f"Recording started to {fname}")
            return True
        except IOError as e:
            print(f"Error opening file for recording: {e}")
            return False

    def stop(self):
        if not self.is_recording: return
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None
        self.is_recording = False
        print("Recording stopped.")

    def record_event(self, xydata, vline, lines_visibility):
        if not self.is_recording: return

        time_s = str(time.time())
        state = self.state

        for c in range(state.num_board * state.num_chan_per_board):
            if lines_visibility[c]:
                line = [
                    str(state.nevents),
                    time_s,
                    str(c),
                    str(vline * state.nsunits),
                    str(state.downsamplefactor / state.samplerate),
                    str(len(xydata[c][1]))
                ]
                self.file_handle.write(",".join(line) + ",")
                xydata[c][1].tofile(self.file_handle, ",", format="%.3f")
                self.file_handle.write("\n")