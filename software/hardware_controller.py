# hardware_controller.py

import os
from concurrent.futures import ThreadPoolExecutor
from usbs import *
from board import *
from pyqtgraph.Qt import QtCore
from utils import find_longest_zero_stretch

class HardwareControllerSignals(QtCore.QObject):
    critical_error_occurred = QtCore.pyqtSignal(str, str) # title, message

class HardwareController:
    """Handles all direct communication with the Haasoscope hardware."""

    def __init__(self, usbs, state):
        self.usbs = usbs
        self.state = state
        self.num_board = len(usbs)
        self.signals = HardwareControllerSignals()
        self.use_external_clock = [False] * self.num_board
        # Thread pool for parallel board operations - use enough threads for all boards
        self.executor = ThreadPoolExecutor(max_workers=max(4, self.num_board * 2))
        self.got_exception = False

    def setup_all_boards(self):
        success = True
        for i, usb in enumerate(self.usbs):
            if not self.setup_connection(i, usb):
                print(f"FATAL: Failed to set up board {i}!")
                success = False
            if i==0 and clockused(usb,i,False): # make sure board 0 is on its internal clock
                self.force_switch_clocks(i)
        if success:
            if not self.use_ext_trigs():
                success = False
            self.tell_downsample_all(self.state.downsample)
        return success

    def setup_connection(self, board_idx, usb):
        print(f"Setting up board {board_idx}")
        ver = version(usb, False)
        self.state.firmwareversion[board_idx] = ver
        if self.state.softwareversion < ver < 1000000: # don't worry about dummy firmware versions, but do fail if the real board firmware is newer than this software
            print("Error - this board has newer firmware than this software!")
            return false
        if ver < max(self.state.firmwareversion):
            print("Warning - this board has older firmware than another being used:",max(self.state.firmwareversion))
        if ver > min(self.state.firmwareversion) > -1:
            print("Warning - this board has newer firmware than another being used:",min(self.state.firmwareversion))
        if 32 <= ver < 1000000:
            ver_minor = version_minor(usb, False)
            self.state.firmwareversion_minor = ver_minor
        if not self.adfreset(board_idx):
            return False
        if not setupboard(usb, self.state.dopattern, self.state.dotwochannel[board_idx], self.state.dooverrange, self.state.basevoltage == 200):
            return False
        for c in range(self.state.num_chan_per_board):
            setchanacdc(usb, c, False, self.state.dooversample[board_idx])
            setchanimpedance(usb, c, False, self.state.dooversample[board_idx])
            setchanatt(usb, c, False, self.state.dooversample[board_idx])
        setsplit(usb, False)
        self.pllreset(board_idx)
        auxoutselector(usb, 0)

        # --- RESTORED POWER SUPPLY HEALTH CHECK ---
        #print(f"  Performing power supply check for board {board_idx}...")
        # Turn everything off to get a baseline reading
        setfan(usb, False)
        send_leds(usb, 0, 0, 0, 0, 0, 0)
        time.sleep(0.9)
        oldtemp, _ = gettemps(usb)

        # Turn everything on to maximize current draw
        for c in range(self.state.num_chan_per_board):
            setchanimpedance(usb, c, True, self.state.dooversample[board_idx])
            setchanatt(usb, c, True, self.state.dooversample[board_idx])
        setsplit(usb, True)
        setfan(usb, True)
        send_leds(usb, 255, 255, 255, 255, 255, 255)
        time.sleep(0.1)
        newtemp, _ = gettemps(usb)

        # Reset all channels back to their default state
        for c in range(self.state.num_chan_per_board):
            setchanimpedance(usb, c, False, self.state.dooversample[board_idx])
            setchanatt(usb, c, False, self.state.dooversample[board_idx])
        setsplit(usb, False)

        # Check for a significant voltage drop (a large negative diff)
        difftemp = newtemp - oldtemp
        print(f"ADC Temp/Voltage Check: Start={oldtemp:.2f}, Load={newtemp:.2f}, Diff={difftemp:.2f}")
        if difftemp < -0.3:
            print(f"!! WARNING: Potential power supply issue on board {board_idx}. Voltage sag detected.")
            return False  # Indicate that this board's setup failed
        # --- END OF HEALTH CHECK ---

        return True

    def adfreset(self, board_idx):
        usb = self.usbs[board_idx]
        adf4350(usb, self.state.samplerate * 1000 / 2, None, themuxout=True)
        time.sleep(0.1)
        res = boardinbits(usb)
        if not getbit(res, 5):
            print(f"Adf pll for board {board_idx} not locked!")
            return False
        else:
            print(f"Adf pll locked for board {board_idx}")
            return True

    def pllreset(self, board_idx):
        """Sends PLL reset and correctly updates the state to start the adjustclocks sequence."""
        usb = self.usbs[board_idx]
        usb.send(bytes([5, 99, 99, 99, 100, 100, 100, 100]))
        usb.recv(4)
        print(f"Pll reset sent to board {board_idx}")
        s = self.state
        if all(x == -10 for x in s.plljustreset): s.depth_before_pllreset = s.expect_samples  # make sure we're the first board doing pllreset
        s.phasecs[board_idx] = [[0] * 5 for _ in range(4)]
        s.plljustresetdir[board_idx] = 1
        s.phasenbad[board_idx] = [0] * 12
        s.expect_samples = 1000
        s.dodrawing = False
        # Enable trigger echo mode for multi-board external trigger calibration
        if self.num_board > 1 and s.doexttrig[board_idx]:
            s.doexttrigecho[board_idx] = True

        # Only do real pllreset for real boards. It breaks the dummy server!
        s.plljustreset[board_idx] = -2 if hasattr(usb,"socket_addr") else 0 # CRITICAL: This starts the calibration

    def adjustclocks(self, board, nbadclkA, nbadclkB, nbadclkC, nbadclkD, nbadstr, main_window):
        """
        The feedback loop that adjusts clock phases based on bad signal counts,
        run immediately after a PLL reset.
        """
        s = self.state
        plloutnum, plloutnum2 = 0, 1  # clklvds and clklvdsout

        if 0 <= s.plljustreset[board] < 12:  # Phase sweep to find good range
            nbad = nbadclkA + nbadclkB + nbadclkC + nbadclkD + nbadstr
            s.phasenbad[board][s.plljustreset[board]] += nbad
            self.do_phase(board, plloutnum, (s.plljustresetdir[board] == 1), pllnum=0, quiet=True)
            self.do_phase(board, plloutnum2, (s.plljustresetdir[board] == 1), pllnum=0, quiet=True)
            s.plljustreset[board] += s.plljustresetdir[board]

        elif s.plljustreset[board] >= 12:  # Overshoot slightly to ensure we find the end of the good range
            if s.plljustreset[board] == 15: s.plljustresetdir[board] = -1
            s.plljustreset[board] += s.plljustresetdir[board]
            self.do_phase(board, plloutnum, (s.plljustresetdir[board] == 1), pllnum=0, quiet=True)
            self.do_phase(board, plloutnum2, (s.plljustresetdir[board] == 1), pllnum=0, quiet=True)

        elif s.plljustreset[board] == -1:  # End of sweep, now analyze and set the optimal phase
            #print(f"Board {board} clkstr errors per phase step: {s.phasenbad[board]}")
            start, length = find_longest_zero_stretch(s.phasenbad[board], True)
            print(f"Found good pll phase range for board {board}: starting at {start} for {length} steps.")

            if length < 4:
                error_title = "PLL Calibration Failed"
                error_message = (f"Board {board} failed PLL calibration.\n\n"
                                 "This is often a hardware or power supply issue. "
                                 "Please check all connections and restart the application.")
                # Emit the signal to notify the main window
                self.signals.critical_error_occurred.emit(error_title, error_message)

                s.plljustreset[board] = -10  # End calibration
                return

            # Go to the middle of the good range
            n_steps = start + length // 2 + 1
            for i in range(n_steps):
                self.do_phase(board, plloutnum, 1, pllnum=0, quiet=True) #(i != n_steps - 1))
                self.do_phase(board, plloutnum2, 1, pllnum=0, quiet=True) #(i != n_steps - 1))
            s.plljustreset[board] -= 1

        elif s.plljustreset[board] == -2:  # Second to last step
            s.expect_samples = s.depth_before_pllreset  # Restore the original sample depth
            s.plljustreset[board] -= 1

        elif s.plljustreset[board] == -3:  # Final step for the current board
            # Mark this board as finished
            s.plljustreset[board] = -10
            #print(f"PLL calibration for board {board} is complete.")

            # Check if ALL boards have finished their calibration sequences.
            all_calibrations_finished = all(status == -10 for status in s.plljustreset)

            # Only re-enable drawing if no other board is still calibrating.
            if all_calibrations_finished:
                s.dodrawing = True

                # Show trigger lines and arrows now that calibration is complete
                main_window.plot_manager.show_trigger_lines()

                # Sync the Depth box UI with the state, in case it was changed by a PLL reset
                main_window.sync_depth_ui_from_state()

    def update_fan(self, fan_override=-1):
        """Sets the fan PWM duty cycle on all boards."""
        for board_idx in range(self.num_board):
            adc_temp, board_temp = gettemps(self.usbs[board_idx])
            #print("Got temps adc board", adc_temp, board_temp)
            fanpwm = 0 # off
            if adc_temp>30: fanpwm = 185 # low
            if adc_temp>40: fanpwm = 195 # medium
            if adc_temp>50: fanpwm = 255 # high
            if 0 <= fan_override < 256: fanpwm = fan_override
            setfanpwm(self.usbs[board_idx],fanpwm,True)

    def send_trigger_info_all(self):
        """Sends the current trigger info to all connected boards."""
        for i in range(self.num_board):
            self.send_trigger_info(i)
            self.send_trigger_delay(i)

    def tell_downsample_all(self, ds, highres=1):
        """Sends the current downsample setting to all connected boards."""
        for i in range(self.num_board):
            self.tell_downsample(self.usbs[i], ds, i, highres)

    def send_trigger_info(self, board_idx):
        state = self.state
        triggerpos = state.triggerpos + state.triggershift
        if state.doexttrig[board_idx]:
            factor = 2 if state.dotwochannel[board_idx] else 1
            triggerpos += int(8 * state.lvdstrigdelay[board_idx] / 40 / state.downsamplefactor / factor)

        delta2 = state.triggerdelta2[board_idx]
        if state.triggerdelta[board_idx] + delta2 >=128: delta2=128 # disable runt trigger if the runt threshold would be too high
        self.usbs[board_idx].send(bytes([8, min(255,state.triggerlevel+1), state.triggerdelta[board_idx],
                                         int(triggerpos / 256), triggerpos % 256,
                                         state.triggertimethresh[board_idx], state.triggerchan[board_idx],
                                         delta2]))
        self.usbs[board_idx].recv(4)
        prelengthtotake = state.triggerpos + 5
        self.usbs[board_idx].send(bytes([2, 7] + inttobytes(prelengthtotake) + [0, 0]))
        self.usbs[board_idx].recv(4)

    def send_trigger_delay(self, board_idx):
        trigger_delay = self.state.trigger_delay[board_idx]
        trigger_holdoff = self.state.trigger_holdoff[board_idx]
        self.usbs[board_idx].send(bytes([2, 20, trigger_delay, trigger_holdoff, 0,0,0,0]))
        self.usbs[board_idx].recv(4)

    def tell_downsample(self, usb, ds, board, highres=1):
        state = self.state
        merging = 1
        if ds < 0: ds = 0
        if ds == 0:
            merging = 1
        elif ds == 1:
            ds, merging = 0, 2
        elif ds == 2:
            ds, merging = 0, 4
        elif ds == 3:
            ds, merging = 0, 8 if not state.dotwochannel[board] else 10
        elif ds == 4:
            ds, merging = 0, 20
        elif not state.dotwochannel[board] and ds == 5:
            ds, merging = 0, 40
        elif not state.dotwochannel[board] and ds > 5:
            ds, merging = ds - 5, 40
        elif state.dotwochannel[board] and ds > 4:
            ds, merging = ds - 4, 20

        state.downsamplemerging = merging
        state.downsamplefactor = state.downsamplemerging * pow(2, ds)

        usb.send(bytes([9, ds, highres, state.downsamplemerging, 100, 100, 100, 100]))
        usb.recv(4)

    def set_channel_gain(self, board_idx, chan_idx, value):
        setgain(self.usbs[board_idx], chan_idx, value, self.state.dooversample[board_idx])

    def set_channel_offset(self, board_idx, chan_idx, value, scaling):
        dooffset(self.usbs[board_idx], chan_idx, value, scaling, self.state.dooversample[board_idx])

    def set_acdc(self, board_idx, chan_idx, is_ac):
        setchanacdc(self.usbs[board_idx], chan_idx, is_ac, self.state.dooversample[board_idx])

    def set_mohm(self, board_idx, chan_idx, is_mohm):
        setchanimpedance(self.usbs[board_idx], chan_idx, is_mohm, self.state.dooversample[board_idx])

    def set_att(self, board_idx, chan_idx, is_att):
        setchanatt(self.usbs[board_idx], chan_idx, is_att, self.state.dooversample[board_idx])

    def set_oversampling(self, board_idx, is_oversampling):
        setsplit(self.usbs[board_idx], is_oversampling)
        setsplit(self.usbs[board_idx + 1], False)
        for i in [board_idx, board_idx + 1]:
            swapinputs(self.usbs[i], is_oversampling)

    def set_tad(self, board_idx, value):
        spicommand(self.usbs[board_idx], "TAD", 0x02, 0xB6, abs(value), False, quiet=True)

    def set_exttrig(self, board_idx, is_ext):
        is_rolling = self.state.isrolling and not is_ext
        self.usbs[board_idx].send(bytes([2, 8, is_rolling, 0, 100, 100, 100, 100]))
        self.usbs[board_idx].recv(4)
        if is_ext:
            # Turn off doexttrigecho for all other boards, turn on for this one
            self.state.doexttrigecho = [False] * self.num_board
            self.state.doexttrigecho[board_idx] = True
        else:
            # Turn off doexttrigecho for this board since it's not doing exttrig anymore
            self.state.doexttrigecho[board_idx] = False
        self.send_trigger_info(board_idx)

    def set_auxout(self, board_idx, value):
        auxoutselector(self.usbs[board_idx], value)

    def dophase(self, board_idx, plloutnum, updown, pllnum=0, quiet=False):
        """Adjust PLL phase for clock alignment.

        Args:
            board_idx: Board index
            plloutnum: PLL output number (0=clklvds, 1=clklvdsout, etc.)
            updown: 1 for up (increase phase), 0 for down (decrease phase)
            pllnum: PLL number (default 0)
            quiet: Suppress print output
        """
        # Command 6: clock phase adjustment
        # 3rd byte: counter select: 000:all 001:M 010=2:C0 011=3:C1 100=4:C2 101=5:C3 110=6:C4
        # 4th byte: 1=up, 0=down
        self.usbs[board_idx].send(bytes([6, pllnum, int(plloutnum + 2), updown, 100, 100, 100, 100]))
        # Note: Response is ignored in v29, so we read and discard
        self.usbs[board_idx].recv(4)
        if not quiet:
            direction = "up" if updown else "down"
            print(f"Adjusted phase {direction} for PLL{pllnum} output {plloutnum} on board {board_idx}")

    def set_rolling(self, is_rolling):
        for i, usb in enumerate(self.usbs):
            r = is_rolling
            if self.state.doexttrig[i]: r = False
            usb.send(bytes([2, 8, r, 0, 100, 100, 100, 100]))
            usb.recv(4)

    def get_event(self):
        state = self.state
        if state.paused:
            time.sleep(.1)
            return None, 0

        ready_event = [False] * self.num_board

        # Process ext trig boards in parallel first using thread pool
        def process_board(board):
            try:
                if self._get_channels(board):  # sends trigger info and checks for ready data
                    ready_event[board] = True
                    self._get_predata(board)  # gets downsamplemergingcounter and triggerphase
            except:
                print("Exception doing board pre-data!")
                self.got_exception = True

        futures = []
        for board in range(self.num_board):
            if state.doexttrig[board]:
                futures.append(self.executor.submit(process_board, board))

        # Wait for all ext trig boards to complete
        for f in futures:
            f.result()

        # Then process non-ext trig boards in parallel using thread pool
        futures = []
        for board in range(self.num_board):
            if not state.doexttrig[board]:
                futures.append(self.executor.submit(process_board, board))

        # Wait for all non-ext trig boards to complete
        for f in futures:
            f.result()

        if not any(ready_event):
            return None, 0

        # Get data from all ready boards in parallel using thread pool
        thedata = [bytes([])] * self.num_board

        def get_board_data(board):
            try:
                if ready_event[board]:
                    data = self._get_data(self.usbs[board])  # gets the actual event data
                    thedata[board] = data
            except:
                print("Exception getting board data!")
                self.got_exception = True

        futures = []
        for board in range(self.num_board):
            futures.append(self.executor.submit(get_board_data, board))

        # Wait for all data retrieval to complete
        for f in futures:
            f.result()

        # Build data_map and find noextboard (sequential to maintain order)
        data_map, total_len = {}, 0
        state.noextboard = -1
        for board in range(self.num_board):
            if not ready_event[board]: continue
            data = thedata[board]
            data_map[board] = data
            total_len += len(data)
            if not state.doexttrig[board]:
                if state.noextboard == -1:
                    state.noextboard = board  # remember the first board which is self-triggering
        return (data_map, total_len) if data_map else (None, 0)

    def _get_channels(self, board_idx):
        state = self.state
        tt = state.triggertype[board_idx]
        if state.doexttrig[board_idx] > 0:
            if state.doexttrigecho[board_idx]:
                tt = 30
            else:
                tt = 3
        elif state.doextsmatrig[board_idx] > 0:
            tt = 5

        is_two_channel = state.dotwochannel[board_idx]

        self.usbs[board_idx].send(bytes([1, tt, is_two_channel + 2 * state.dooversample[board_idx], 99] +
                                       inttobytes(state.expect_samples + state.expect_samples_extra - state.triggerpos + 1)))
        triggercounter = self.usbs[board_idx].recv(4)

        if triggercounter[0] == 251: # Event ready
            state.sample_triggered[board_idx] = triggercounter[1]
            return True
        return False

    def _get_predata(self, board_idx):
        state = self.state
        self.usbs[board_idx].send(bytes([2, 4, 100, 100, 100, 100, 100, 100]))
        res = self.usbs[board_idx].recv(4)
        if state.downsamplemerging > 1:
            state.downsamplemergingcounter[board_idx] = res[0]
        if state.downsamplemergingcounter[board_idx] == state.downsamplemerging and not state.doexttrig[board_idx]:
            state.downsamplemergingcounter[board_idx] = 0
        state.triggerphase[board_idx] = res[1]

        # Handle external trigger echo delay calculation
        if not state.doexttrig[board_idx] and any(state.doexttrigecho):
            assert state.doexttrigecho.count(True) == 1, "Should only have one echoing board"

            # Find the board we're echoing from
            echoboard = -1
            for theb in range(self.num_board):
                if state.doexttrigecho[theb]:
                    assert echoboard == -1, "Should only have one echoing board"
                    echoboard = theb

            assert echoboard != board_idx, "Echo board should not be current board"

            # Get the trigger delay measurement from firmware
            if echoboard > board_idx:
                # Forward echo: use Command 2, Subcommand 12 (phase_diff)
                self.usbs[board_idx].send(bytes([2, 12, 100, 100, 100, 100, 100, 100]))
                res = self.usbs[board_idx].recv(4)
            else:
                # Backward echo: use Command 2, Subcommand 13 (phase_diff_b)
                self.usbs[board_idx].send(bytes([2, 13, 100, 100, 100, 100, 100, 100]))
                res = self.usbs[board_idx].recv(4)

            # Check if phase measurements are consistent
            if res[0] == res[1]:
                # Calculate delay in LVDS clock cycles
                lvdstrigdelay = (res[0] + res[1]) / 4
                if echoboard < board_idx:
                    # Backward echo needs tuning adjustment - this has to be tuned a little experimentally
                    lvdstrigdelay += round(lvdstrigdelay / 11.5, 1)

                # Check if delay is consistent with last measurement
                if lvdstrigdelay == state.lastlvdstrigdelay[echoboard]:
                    state.lvdstrigdelay[echoboard] = lvdstrigdelay
                    # Delay is stable, turn off echo mode
                    print(f"lvdstrigdelay from board {board_idx} to echoboard {echoboard} is {lvdstrigdelay}")
                    state.doexttrigecho[echoboard] = False

                state.lastlvdstrigdelay[echoboard] = lvdstrigdelay
            else:
                # Phase measurements don't match - need to adjust phase alignment
                # Only adjust phases after PLL calibration is complete to avoid interfering with ADC sampling phase calibration
                if all(item <= -10 for item in state.plljustreset):
                    # Adjust both clklvds (0) and clklvdsout (1) to align trigger signals
                    self.dophase(board_idx, plloutnum=0, updown=1, quiet=True)
                    self.dophase(board_idx, plloutnum=1, updown=1, quiet=True)

    def _get_data(self, usb):
        expect_len = (self.state.expect_samples + self.state.expect_samples_extra) * 2 * 50
        usb.send(bytes([0, 99, 99, 99] + inttobytes(expect_len)))
        data = usb.recv(expect_len)
        if len(data) != expect_len:
            print(f'*** expect_len ({expect_len}) and rx_len ({len(data)}) mismatch')
        return data

    def use_ext_trigs(self):
        for board in range(1, self.num_board):
            self.state.doexttrig[board] = True
            usb = self.usbs[board]

            # Skip dummy boards
            if isinstance(usb, UsbSocketAdapter): continue

            # Try to set the clock to external
            if not clockused(usb,board,quiet=True): # returns True if on external clock
                if not self.force_switch_clocks(board): # ask to switch to external
                    print(f"FATAL: Failed to set board {board} to external clock!")
                    return False
            else:
                print(f"Board {board} already locked to external clock")
                self.use_external_clock[board] = True

            # Actually turn on ext trigs
            usb.send(bytes([2, 8, False, 0, 100, 100, 100, 100]))
            usb.recv(4)
            self.send_trigger_info(board)
        return True

    def set_channel_gain_offset(self, board_idx, chan_idx, gain, offset):
        state = self.state
        setgain(self.usbs[board_idx], chan_idx, gain, state.dooversample[board_idx])
        scaling = 1000 * state.VperD[state.activexychannel] / 160
        if state.acdc[state.activexychannel]: scaling *= 245 / 160
        dooffset(self.usbs[board_idx], chan_idx, offset, scaling / state.tenx[state.activexychannel],
                 state.dooversample[board_idx])

    def do_phase(self, board, plloutnum, updown, pllnum, quiet=False):
        self.usbs[board].send(bytes([6, pllnum, int(plloutnum + 2), updown, 100, 100, 100, 100]))
        if updown:
            self.state.phasecs[board][pllnum][plloutnum] += 1
        else:
            self.state.phasecs[board][pllnum][plloutnum] -= 1
        if not quiet: print(
            f"phase for pllnum {pllnum} plloutnum {plloutnum} on board {board} now {self.state.phasecs[board][pllnum][plloutnum]}")

    def update_firmware(self, board_idx, verify_only=False, progress_callback=None):
        print(f"Starting firmware update on board {board_idx}...")
        firmwarepath = "../adc board firmware/output_files/coincidence_auto.rpd"
        if not os.path.exists(firmwarepath):
            firmwarepath = "../../../adc board firmware/output_files/coincidence_auto.rpd"
            if not os.path.exists(firmwarepath):
                print("coincidence_auto.rpd was not found!")
                return False, "Firmware file not found."

        starttime = time.time()

        # disable clkout on all boards
        for i in reversed(range(self.num_board)): clkout_ena(self.usbs[i], i, False)
        time.sleep(.1)

        if not verify_only:
            if progress_callback:
                progress_callback("Erasing flash...", 0, 100)
            print("Erasing flash...")
            flash_erase(self.usbs[board_idx])
            # Poll flash_busy and update progress
            busy_count = 0
            while flash_busy(self.usbs[board_idx], doprint=False) > 0:
                time.sleep(.1)
                busy_count += 1
                if progress_callback and busy_count % 5 == 0:  # Update every 0.5 seconds
                    progress_callback("Erasing flash...", min(busy_count, 90), 100)
            print(f"Erase took {time.time() - starttime:.3f} seconds.")
            if progress_callback:
                progress_callback("Erase complete", 100, 100)

        # Writing firmware with progress
        if not verify_only:
            if progress_callback:
                progress_callback("Writing firmware...", 0, 100)
            print("Writing firmware...")

            def write_progress(current, total):
                if progress_callback:
                    percent = int(100 * current / total)
                    progress_callback(f"Writing firmware... ({current}/{total} bytes)", percent, 100)

            writtenbytes = flash_writeall_from_file(self.usbs[board_idx], firmwarepath,
                                                    do_write=True, progress_callback=write_progress)
            print(f"Write took {time.time() - starttime:.3f} seconds total.")
        else:
            # For verify-only, just read the file
            writtenbytes = flash_writeall_from_file(self.usbs[board_idx], firmwarepath, do_write=False)

        # Verifying with progress
        if progress_callback:
            progress_callback("Verifying...", 0, 100)
        print("Verifying write...")

        def verify_progress(current, total):
            if progress_callback:
                percent = int(100 * current / total)
                progress_callback(f"Verifying... (block {current}/{total})", percent, 100)

        readbytes = flash_readall(self.usbs[board_idx], progress_callback=verify_progress)

        # reanable clkout for all but the last board
        for i in range(self.num_board): clkout_ena(self.usbs[i], i, i<(self.num_board-1) )

        if writtenbytes == readbytes:
            print("Verified!")
            if progress_callback:
                progress_callback("Verified!", 100, 100)
            if verify_only:
                return True, f"Verified! Update took {time.time() - starttime:.3f}s."
            else:
                reload_firmware(self.usbs[board_idx])
                return True, f"Verified! Update took {time.time() - starttime:.3f}s. Restart software."
        else:
            print("Verification failed!")
            if progress_callback:
                progress_callback("Verification failed!", 100, 100)
            return False, "Verification failed!"

    def force_split(self, board_idx, is_split):
        """Directly commands the clock splitter state."""
        setsplit(self.usbs[board_idx], is_split)

    def force_switch_clocks(self, board_idx):
        """Directly commands a clock switch."""
        clock_wanted = not self.use_external_clock[board_idx]
        if clock_wanted: print(f"Trying to switch board {board_idx} to external clock")
        else: print(f"Trying to switch board {board_idx} to internal clock")
        if switchclock(self.usbs[board_idx], board_idx, clock_wanted):
            self.use_external_clock[board_idx] = clock_wanted
            if self.use_external_clock[board_idx]: print(f"Board {board_idx} now locked to external clock")
            else: print(f"Board {board_idx} now locked to internal clock")
            return True # Successfully switched
        print(f"Board {board_idx} was unable to switch clocks")
        return False

    def do_leds(self, channel_colors):
        """
        Calculates and sends the correct RGB values to the LEDs on each board
        based on the current channel colors and board states.

        Args:
            channel_colors (list): A list of QColor objects for all channels.
        """
        state = self.state
        for board in range(self.num_board):
            # Get the base color for channel 0 on this board
            c1_idx = board * state.num_chan_per_board
            col1 = channel_colors[c1_idx]
            r1, g1, b1 = col1.red(), col1.green(), col1.blue()

            # Default for channel 1 LED is off
            r2, g2, b2 = 0, 0, 0

            if state.dotwochannel[board]:
                # In two-channel mode, get the color for channel 1
                c2_idx = c1_idx + 1
                col2 = channel_colors[c2_idx]
                r2, g2, b2 = col2.red(), col2.green(), col2.blue()

            if state.dooversample[board]:
                # In oversample mode, LED 1 is off, and LED 2 takes the color of LED 1
                r2, g2, b2 = r1, g1, b1
                r1, g1, b1 = 0, 0, 0

            if state.dointerleaved[board] and board % 2 == 1:
                # For the second board in an interleaved pair,
                # its LED 2 is a dimmed version of the primary board's LED 1 color.
                primary_board_c1_idx = (board - 1) * state.num_chan_per_board
                col1_primary = channel_colors[primary_board_c1_idx]
                dim_factor = 10.0
                r2 = int(col1_primary.red() / dim_factor)
                g2 = int(col1_primary.green() / dim_factor)
                b2 = int(col1_primary.blue() / dim_factor)

            # Send the final calculated RGB values to the hardware
            send_leds(self.usbs[board], r1, g1, b1, r2, g2, b2)

    def cleanup(self):
        self.executor.shutdown(wait=True)
        for usb in self.usbs:
            cleanup(usb)
