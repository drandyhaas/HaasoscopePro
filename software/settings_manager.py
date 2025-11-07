# settings_manager.py
"""Handles saving and loading scope setup configurations to/from JSON files."""

import sys, os
import json
from PyQt5.QtWidgets import QMessageBox, QFileDialog, QListWidgetItem
from PyQt5.QtGui import QColor
from math_channels_window import MathChannelsWindow
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore


def save_setup(main_window):
    """Save current scope setup to a JSON file.

    Args:
        main_window: The MainWindow instance containing all scope state
    """
    options = QFileDialog.Options()
    if sys.platform.startswith('linux'):
        options |= QFileDialog.DontUseNativeDialog
    filename, _ = QFileDialog.getSaveFileName(
        main_window, "Save Setup", "", "JSON Files (*.json);;All Files (*)", options=options
    )
    if not filename:
        return

    if not os.path.splitext(filename)[1]:  # Check if there's no extension
        filename += ".json"

    s = main_window.state

    # Collect all settings to save
    setup = {
        # Timebase and acquisition
        'downsample': s.downsample,
        'expect_samples': s.expect_samples,
        'isrolling': s.isrolling,
        'getone': s.getone,

        # Active board/channel
        'activeboard': s.activeboard,
        'selectedchannel': s.selectedchannel,

        # Trigger settings (per-board arrays)
        'triggerlevel': s.triggerlevel,
        'triggerdelta': s.triggerdelta,
        'triggerdelta2': s.triggerdelta2,
        'triggerpos': s.triggerpos,
        'triggerchan': s.triggerchan,
        'fallingedge': s.fallingedge,
        'triggertype': s.triggertype,
        'triggertimethresh': s.triggertimethresh,
        'trigger_delay': s.trigger_delay,
        'trigger_holdoff': s.trigger_holdoff,
        'doexttrig': s.doexttrig,
        'doextsmatrig': s.doextsmatrig,

        # Channel settings (per-channel arrays)
        'gain': s.gain,
        'offset': s.offset,
        'acdc': s.acdc,
        'mohm': s.mohm,
        'att': s.att,
        'tenx': s.tenx,
        'lpf': s.lpf,
        'time_skew': s.time_skew,
        'channel_names': s.channel_names,

        # Board mode settings
        'dotwochannel': s.dotwochannel,
        'dooversample': s.dooversample,
        'dointerleaved': s.dointerleaved,

        # TAD settings (per-board)
        'tad': s.tad,
        'toff': s.toff,
        'auxoutval': s.auxoutval,

        # Display settings
        'dodrawing': s.dodrawing,
        'downsamplezoom': s.downsamplezoom,
        'min_x': s.min_x,
        'max_x': s.max_x,
        'xy_mode': s.xy_mode,

        # XY window settings
        'xy_window_visible': main_window.xy_window is not None and main_window.xy_window.isVisible() if main_window.xy_window else False,
    }

    # Save XY window geometry and channel selections if window exists
    if main_window.xy_window is not None:
        setup['xy_window_geometry'] = {
            'x': main_window.xy_window.x(),
            'y': main_window.xy_window.y(),
            'width': main_window.xy_window.width(),
            'height': main_window.xy_window.height(),
        }
        setup['xy_window_y_channel'] = main_window.xy_window.y_channel
        setup['xy_window_x_channel'] = main_window.xy_window.x_channel

    # Save Zoom window state
    setup['zoom_window_visible'] = main_window.zoom_window is not None and main_window.zoom_window.isVisible() if main_window.zoom_window else False

    # Save Zoom window geometry if window exists
    if main_window.zoom_window is not None:
        setup['zoom_window_geometry'] = {
            'x': main_window.zoom_window.x(),
            'y': main_window.zoom_window.y(),
            'width': main_window.zoom_window.width(),
            'height': main_window.zoom_window.height(),
        }
        # Save zoom ROI position and size
        if main_window.plot_manager.zoom_roi is not None:
            roi_pos = main_window.plot_manager.zoom_roi.pos()
            roi_size = main_window.plot_manager.zoom_roi.size()
            setup['zoom_roi_geometry'] = {
                'x': roi_pos[0],
                'y': roi_pos[1],
                'width': roi_size[0],
                'height': roi_size[1],
            }

    # Continue with other settings
    setup.update({
        # Processing settings
        'doresamp': s.doresamp,
        'saved_doresamp': s.saved_doresamp,
        'fitwidthfraction': s.fitwidthfraction,

        # FFT and reference settings
        'fft_enabled': s.fft_enabled,
        'reference_visible': main_window.reference_visible,
        'math_reference_visible': main_window.math_reference_visible,
        'show_reference': main_window.ui.actionShow_Reference.isChecked(),

        # Plot manager settings
        'line_width': main_window.state.line_width,

        # Per-channel persistence settings
        'persist_time': main_window.state.persist_time,
        'persist_lines_enabled': main_window.state.persist_lines_enabled,
        'persist_avg_enabled': main_window.state.persist_avg_enabled,
        'persist_heatmap_enabled': main_window.state.persist_heatmap_enabled,
        'heatmap_smoothing_sigma': main_window.plot_manager.heatmap_manager.heatmap_smoothing_sigma,

        # Channel enabled state (per-channel, from chanonCheck)
        'channel_enabled': main_window.state.channel_enabled,

        # Channel colors
        'channel_colors': [pen.color().name() for pen in main_window.plot_manager.linepens],

        # View menu states
        'grid_visible': main_window.ui.actionGrid.isChecked(),
        'markers_visible': main_window.ui.actionMarkers.isChecked(),
        'voltage_axis_visible': main_window.ui.actionVoltage_axis.isChecked(),
        'pan_and_zoom': main_window.ui.actionPan_and_zoom.isChecked(),
        'peak_detect_per_channel': main_window.plot_manager.peak_detect_enabled,  # Per-channel dict
        'channel_name_legend': main_window.ui.actionChannel_name_legend.isChecked(),
        'zoom_window_crosshairs': main_window.ui.actionZoom_window_crosshairs.isChecked(),

        # Cursor menu states
        'cursors_visible': main_window.ui.actionCursors.isChecked(),
        'time_relative': main_window.ui.actionTime_relative.isChecked(),
        'snap_to_waveform': main_window.ui.actionSnap_to_waveform.isChecked(),
        'risetime_fit_lines': main_window.ui.actionRisetime_fit_lines.isChecked(),
        'trigger_info': main_window.ui.actionTrigger_info.isChecked(),

        # Measurement menu states
        'measure_mean': main_window.ui.actionMean.isChecked(),
        'measure_rms': main_window.ui.actionRMS.isChecked(),
        'measure_min': main_window.ui.actionMinimum.isChecked(),
        'measure_max': main_window.ui.actionMaximum.isChecked(),
        'measure_vpp': main_window.ui.actionVpp.isChecked(),
        'measure_freq': main_window.ui.actionFreq.isChecked(),
        'measure_period': main_window.ui.actionPeriod.isChecked(),
        'measure_duty_cycle': main_window.ui.actionDuty_cycle.isChecked(),
        'measure_pulse_width': main_window.ui.actionPulse_width.isChecked(),
        'measure_risetime': main_window.ui.actionRisetime.isChecked(),
        'measure_risetime_error': main_window.ui.actionRisetime_error.isChecked(),
        'measure_edge_fit': main_window.ui.actionEdge_fit_method.isChecked(),
        'measure_trig_thresh': main_window.ui.actionTrigger_thresh.isChecked(),
        'measure_n_persist': main_window.ui.actionN_persist_lines.isChecked(),
        'measure_adc_temp': main_window.ui.actionADC_temperature.isChecked(),
        'measure_board_temp': main_window.ui.actionBoard_temperature.isChecked(),

        # Active measurements in table
        'active_measurements': [(k[0], k[1]) for k in main_window.measurements.active_measurements.keys()],

        # Other settings
        'high_resolution': main_window.ui.actionHigh_resolution.isChecked(),
        'trig_stabilizer_enabled': s.trig_stabilizer_enabled,
        'extra_trig_stabilizer_enabled': s.extra_trig_stabilizer_enabled,
        'pulse_stabilizer_enabled': s.pulse_stabilizer_enabled,
        'oversampling_controls': main_window.ui.actionOversampling_controls.isChecked(),
        'pll_controls': main_window.ui.actionToggle_PLL_controls.isChecked(),
        'auto_oversample_alignment': main_window.ui.actionAuto_oversample_alignment.isChecked(),

        # FIR correction settings (coefficients are saved/loaded separately via .fir files)
        'fir_correction_enabled': s.fir_correction_enabled,

        # Polynomial filtering settings
        'polynomial_filtering_enabled': s.polynomial_filtering_enabled,
        'savgol_window_length': s.savgol_window_length,
        'savgol_polyorder': s.savgol_polyorder,

        # Resampling settings
        'polyphase_upsampling_enabled': s.polyphase_upsampling_enabled,
    })

    # Math channels
    if main_window.math_window is not None and len(main_window.math_window.math_channels) > 0:
        setup['math_channels'] = main_window.math_window.math_channels
        setup['math_channels_next_color_index'] = main_window.math_window.next_color_index

    # Custom operations
    if main_window.math_window is not None and len(main_window.math_window.custom_operations) > 0:
        setup['custom_operations'] = main_window.math_window.custom_operations

    try:
        with open(filename, 'w') as f:
            json.dump(setup, f, indent=2)
        print(f"Setup saved to {filename}")
    except Exception as e:
        QMessageBox.warning(main_window, "Save Failed", f"Failed to save setup:\n{e}")


def load_setup(main_window):
    """Load scope setup from a JSON file and restore the state.

    Args:
        main_window: The MainWindow instance to restore state to
    """
    options = QFileDialog.Options()
    if sys.platform.startswith('linux'):
        options |= QFileDialog.DontUseNativeDialog
    filename, _ = QFileDialog.getOpenFileName(
        main_window, "Load Setup", "", "JSON Files (*.json);;All Files (*)", options=options
    )
    if not filename:
        return

    try:
        with open(filename, 'r') as f:
            setup = json.load(f)
    except Exception as e:
        QMessageBox.warning(main_window, "Load Failed", f"Failed to load setup:\n{e}")
        return

    # Pause acquisition during restoration
    was_paused = main_window.state.paused
    if not was_paused:
        main_window.dostartstop()

    s = main_window.state

    # Board mode settings - LOAD THESE FIRST before other settings
    # These affect which channels are available and how the hardware is configured
    if 'dotwochannel' in setup:
        s.dotwochannel = setup['dotwochannel']
    if 'dooversample' in setup:
        s.dooversample = setup['dooversample']
    if 'dointerleaved' in setup:
        s.dointerleaved = setup['dointerleaved']

    # Apply board modes to hardware by reconfiguring each board
    for board_idx in range(s.num_board):
        from board import setupboard
        usb = main_window.controller.usbs[board_idx]
        # Reconfigure the board with the loaded two-channel mode setting
        if not setupboard(usb, s.dopattern, s.dotwochannel[board_idx], s.dooverrange, s.basevoltage == 200):
            print(f"Warning: Failed to reconfigure board {board_idx} with loaded settings")

        # Set oversampling if needed
        if s.dooversample[board_idx] and board_idx % 2 == 0:
            main_window.controller.set_oversampling(board_idx, True)
            # Set external trigger for second board in oversampling pair
            s.doexttrig[board_idx + 1] = True
            main_window.controller.set_exttrig(board_idx + 1, True)

        # Update channel enabled states for interleaved mode
        if s.dointerleaved[board_idx] and board_idx % 2 == 0:
            # Disable secondary board's channels when interleaved
            c_secondary_ch0 = (board_idx + 1) * s.num_chan_per_board
            c_secondary_ch1 = c_secondary_ch0 + 1
            s.channel_enabled[c_secondary_ch0] = False
            s.channel_enabled[c_secondary_ch1] = False

    # Restore state variables
    # Timebase and acquisition
    if 'downsample' in setup:
        s.downsample = setup['downsample']
        # Note: tell_downsample_all will be called later after high_resolution is restored
    if 'expect_samples' in setup:
        s.expect_samples = setup['expect_samples']
        main_window.ui.depthBox.setValue(s.expect_samples)
    if 'isrolling' in setup:
        s.isrolling = setup['isrolling']
        main_window.controller.set_rolling(s.isrolling)
        main_window.ui.rollingButton.setChecked(s.isrolling)
        main_window.ui.rollingButton.setText("Auto" if s.isrolling else "Normal")
    if 'getone' in setup:
        s.getone = setup['getone']
        main_window.ui.singleButton.setChecked(s.getone)

    # Trigger settings
    if 'triggerlevel' in setup:
        s.triggerlevel = setup['triggerlevel']
        main_window.ui.threshold.setValue(s.triggerlevel)
    if 'triggerdelta' in setup:
        s.triggerdelta = setup['triggerdelta']
        main_window.ui.thresholdDelta.setValue(s.triggerdelta[s.activeboard])
    if 'triggerdelta2' in setup:
        s.triggerdelta2 = setup['triggerdelta2']
        main_window.ui.thresholdDelta_2.setValue(s.triggerdelta2[s.activeboard])
    if 'triggerpos' in setup:
        s.triggerpos = setup['triggerpos']
        # Calculate slider value from triggerpos
        slider_val = int(s.triggerpos * 10000. / s.expect_samples)
        main_window.ui.thresholdPos.setValue(slider_val)
    if 'triggerchan' in setup:
        s.triggerchan = setup['triggerchan']
    if 'fallingedge' in setup:
        s.fallingedge = setup['fallingedge']
    if 'triggertype' in setup:
        s.triggertype = setup['triggertype']

    # Update rising/falling combo box based on loaded trigger settings
    if 'fallingedge' in setup and 'triggerchan' in setup:
        # Calculate combo box index: 0=Rising(Ch0), 1=Falling(Ch0), 2=Rising(Ch1), 3=Falling(Ch1)
        combo_index = s.fallingedge[s.activeboard] + (2 * s.triggerchan[s.activeboard])
        main_window.ui.risingfalling_comboBox.blockSignals(True)
        main_window.ui.risingfalling_comboBox.setCurrentIndex(combo_index)
        main_window.ui.risingfalling_comboBox.blockSignals(False)

    if 'triggertimethresh' in setup:
        s.triggertimethresh = setup['triggertimethresh']
        main_window.ui.totBox.setValue(s.triggertimethresh[s.activeboard])
    if 'trigger_delay' in setup:
        s.trigger_delay = setup['trigger_delay']
        main_window.ui.trigger_delay_box.setValue(s.trigger_delay[s.activeboard])
    if 'trigger_holdoff' in setup:
        s.trigger_holdoff = setup['trigger_holdoff']
        main_window.ui.trigger_holdoff_box.setValue(s.trigger_holdoff[s.activeboard])
    if 'doexttrig' in setup:
        s.doexttrig = setup['doexttrig']
    if 'doextsmatrig' in setup:
        s.doextsmatrig = setup['doextsmatrig']

    # Channel settings
    if 'gain' in setup:
        s.gain = setup['gain']
    if 'offset' in setup:
        s.offset = setup['offset']
    if 'acdc' in setup:
        s.acdc = setup['acdc']
    if 'mohm' in setup:
        s.mohm = setup['mohm']
    if 'att' in setup:
        s.att = setup['att']
    if 'tenx' in setup:
        s.tenx = setup['tenx']
    if 'lpf' in setup:
        s.lpf = setup['lpf']
    if 'time_skew' in setup:
        s.time_skew = setup['time_skew']
    if 'channel_names' in setup:
        s.channel_names = setup['channel_names']

    # Board mode settings were already loaded and applied at the beginning of this function

    # TAD settings
    if 'tad' in setup:
        s.tad = setup['tad']
    if 'toff' in setup:
        s.toff = setup['toff']
        main_window.ui.ToffBox.setValue(s.toff)
    if 'auxoutval' in setup:
        s.auxoutval = setup['auxoutval']

    # Display settings
    if 'dodrawing' in setup:
        s.dodrawing = setup['dodrawing']
        main_window.ui.actionDrawing.setChecked(s.dodrawing)
    if 'downsamplezoom' in setup:
        s.downsamplezoom = setup['downsamplezoom']
    if 'min_x' in setup:
        s.min_x = setup['min_x']
    if 'max_x' in setup:
        s.max_x = setup['max_x']

    # Note: xy_mode and XY window restoration moved to after display updates
    # so that channel lists are properly populated based on loaded board modes

    # Processing settings
    if 'saved_doresamp' in setup:
        loaded_saved_doresamp = setup['saved_doresamp']
        # Handle backward compatibility: convert scalar to array
        if isinstance(loaded_saved_doresamp, (int, float)):
            s.saved_doresamp = [int(loaded_saved_doresamp)] * (s.num_board * s.num_chan_per_board)
        else:
            s.saved_doresamp = loaded_saved_doresamp
    if 'doresamp' in setup:
        loaded_doresamp = setup['doresamp']
        # Handle backward compatibility: convert scalar to array
        if isinstance(loaded_doresamp, (int, float)):
            loaded_doresamp = [int(loaded_doresamp)] * (s.num_board * s.num_chan_per_board)

        # If downsample >= 0, force doresamp to 0 and save the loaded value
        if s.downsample >= 0:
            s.saved_doresamp = loaded_doresamp
            s.doresamp = [0] * (s.num_board * s.num_chan_per_board)
        else:
            s.doresamp = loaded_doresamp
        main_window.ui.resampBox.setValue(s.doresamp[s.activexychannel])
    if 'fitwidthfraction' in setup:
        s.fitwidthfraction = setup['fitwidthfraction']

    # FFT and reference settings
    if 'fft_enabled' in setup:
        s.fft_enabled = setup['fft_enabled']
    if 'reference_visible' in setup:
        # Convert string keys to integers
        main_window.reference_visible = {int(k): v for k, v in setup['reference_visible'].items()}
    if 'math_reference_visible' in setup:
        main_window.math_reference_visible = setup['math_reference_visible']
    if 'show_reference' in setup:
        main_window.ui.actionShow_Reference.setChecked(setup['show_reference'])

    # Plot manager settings
    if 'line_width' in setup:
        main_window.state.line_width = setup['line_width']
        main_window.ui.linewidthBox.setValue(setup['line_width'])

    # Load per-channel persistence settings
    if 'persist_time' in setup:
        main_window.state.persist_time = setup['persist_time']
    if 'persist_lines_enabled' in setup:
        persist_lines = setup['persist_lines_enabled']
        # Handle both old (bool) and new (list) formats
        if isinstance(persist_lines, bool):
            # Old format: single bool, apply to all channels
            main_window.state.persist_lines_enabled = [persist_lines] * len(main_window.state.persist_lines_enabled)
        else:
            # New format: per-channel list
            main_window.state.persist_lines_enabled = persist_lines
    if 'persist_avg_enabled' in setup:
        persist_avg = setup['persist_avg_enabled']
        # Handle both old (bool) and new (list) formats
        if isinstance(persist_avg, bool):
            # Old format: single bool, apply to all channels
            main_window.state.persist_avg_enabled = [persist_avg] * len(main_window.state.persist_avg_enabled)
        else:
            # New format: per-channel list
            main_window.state.persist_avg_enabled = persist_avg

    if 'persist_heatmap_enabled' in setup:
        persist_heatmap = setup['persist_heatmap_enabled']
        # Handle both old (bool) and new (list) formats
        if isinstance(persist_heatmap, bool):
            # Old format: single bool, apply to all channels
            main_window.state.persist_heatmap_enabled = [persist_heatmap] * len(main_window.state.persist_heatmap_enabled)
        else:
            # New format: per-channel list
            main_window.state.persist_heatmap_enabled = persist_heatmap

    if 'heatmap_smoothing_sigma' in setup:
        main_window.plot_manager.heatmap_manager.heatmap_smoothing_sigma = setup['heatmap_smoothing_sigma']

    # Sync UI controls to reflect active channel's persistence settings
    main_window.sync_persistence_ui()

    # Initialize persistence timer based on loaded settings
    any_persist_active = any(t > 0 for t in main_window.state.persist_time)
    if any_persist_active:
        if not main_window.plot_manager.persist_timer.isActive():
            main_window.plot_manager.persist_timer.start(50)
    else:
        # Stop timer and clear persist lines if no persistence is active
        if main_window.plot_manager.persist_timer.isActive():
            main_window.plot_manager.persist_timer.stop()
        main_window.plot_manager.clear_persist()
        # Update zoom window to clear persist lines
        if main_window.zoom_window and main_window.zoom_window.isVisible():
            main_window.zoom_window.update_persist_lines(main_window.plot_manager)

    # Channel enabled state (per-channel)
    if 'channel_enabled' in setup:
        main_window.state.channel_enabled = setup['channel_enabled']
    elif 'channel_visible' in setup:
        # Backward compatibility: use old channel_visible as channel_enabled
        main_window.state.channel_enabled = setup['channel_visible']

    # Channel colors
    if 'channel_colors' in setup:
        for idx, color_name in enumerate(setup['channel_colors']):
            if idx < len(main_window.plot_manager.linepens):
                main_window.plot_manager.linepens[idx].setColor(QColor(color_name))
                # Apply the updated pen to the plot line
                if idx < len(main_window.plot_manager.lines):
                    main_window.plot_manager.lines[idx].setPen(main_window.plot_manager.linepens[idx])
                # Update reference line color if a reference exists for this channel
                if idx in main_window.reference_data:
                    main_window.plot_manager.update_reference_line_color(idx)
                # Update peak detect line color if peak detect is enabled for this channel
                if idx in main_window.plot_manager.peak_max_line:
                    base_pen = main_window.plot_manager.linepens[idx]
                    peak_color = base_pen.color()
                    width = base_pen.width()
                    peak_pen = pg.mkPen(color=peak_color, width=width, style=QtCore.Qt.DotLine)
                    main_window.plot_manager.peak_max_line[idx].setPen(peak_pen)
                    main_window.plot_manager.peak_min_line[idx].setPen(peak_pen)

    # View menu states
    if 'grid_visible' in setup:
        main_window.ui.actionGrid.setChecked(setup['grid_visible'])
        main_window.plot_manager.set_grid(setup['grid_visible'])
    if 'markers_visible' in setup:
        main_window.ui.actionMarkers.setChecked(setup['markers_visible'])
        main_window.plot_manager.set_markers(setup['markers_visible'])
    if 'voltage_axis_visible' in setup:
        main_window.ui.actionVoltage_axis.setChecked(setup['voltage_axis_visible'])
        main_window.plot_manager.right_axis.setVisible(setup['voltage_axis_visible'])
    if 'pan_and_zoom' in setup:
        main_window.ui.actionPan_and_zoom.setChecked(setup['pan_and_zoom'])
        main_window.plot_manager.set_pan_and_zoom(setup['pan_and_zoom'])
    if 'zoom_window_crosshairs' in setup:
        main_window.ui.actionZoom_window_crosshairs.setChecked(setup['zoom_window_crosshairs'])
        main_window.plot_manager.set_crosshairs_enabled(setup['zoom_window_crosshairs'])
        if main_window.zoom_window is not None:
            main_window.zoom_window.set_crosshairs_enabled(setup['zoom_window_crosshairs'])

    # Handle both old (single boolean) and new (per-channel dict) peak detect settings
    if 'peak_detect_per_channel' in setup:
        # New format: per-channel dictionary
        loaded_peak_detect = setup['peak_detect_per_channel']
        # Convert channel indices from strings to ints if necessary (JSON serialization)
        main_window.plot_manager.peak_detect_enabled = {int(k): v for k, v in loaded_peak_detect.items()}
        # Restore peak lines for enabled channels by temporarily switching to each channel
        saved_active_channel = s.activexychannel
        for channel_idx, enabled in main_window.plot_manager.peak_detect_enabled.items():
            if enabled:
                s.activexychannel = channel_idx  # Temporarily switch to this channel
                main_window.plot_manager.set_peak_detect(True)
        s.activexychannel = saved_active_channel  # Restore original active channel
        # Update checkbox for active channel
        main_window.update_peak_detect_checkbox_state()
    elif 'peak_detect' in setup:
        # Old format: single boolean for active channel (backward compatibility)
        active_channel = s.activexychannel
        main_window.plot_manager.peak_detect_enabled[active_channel] = setup['peak_detect']
        if setup['peak_detect']:
            main_window.plot_manager.set_peak_detect(True)
        main_window.ui.actionPeak_detect.setChecked(setup['peak_detect'])

    if 'channel_name_legend' in setup:
        main_window.ui.actionChannel_name_legend.setChecked(setup['channel_name_legend'])
        main_window.plot_manager.update_legend()

    # Cursor menu states
    if 'cursors_visible' in setup:
        main_window.ui.actionCursors.setChecked(setup['cursors_visible'])
    if 'time_relative' in setup:
        main_window.ui.actionTime_relative.setChecked(setup['time_relative'])
    if 'snap_to_waveform' in setup:
        main_window.ui.actionSnap_to_waveform.setChecked(setup['snap_to_waveform'])
    if 'risetime_fit_lines' in setup:
        main_window.ui.actionRisetime_fit_lines.setChecked(setup['risetime_fit_lines'])
    if 'trigger_info' in setup:
        main_window.ui.actionTrigger_info.setChecked(setup['trigger_info'])

    # Measurement menu states
    if 'measure_mean' in setup:
        main_window.ui.actionMean.setChecked(setup['measure_mean'])
    if 'measure_rms' in setup:
        main_window.ui.actionRMS.setChecked(setup['measure_rms'])
    if 'measure_min' in setup:
        main_window.ui.actionMinimum.setChecked(setup['measure_min'])
    if 'measure_max' in setup:
        main_window.ui.actionMaximum.setChecked(setup['measure_max'])
    if 'measure_vpp' in setup:
        main_window.ui.actionVpp.setChecked(setup['measure_vpp'])
    if 'measure_freq' in setup:
        main_window.ui.actionFreq.setChecked(setup['measure_freq'])
    if 'measure_period' in setup:
        main_window.ui.actionPeriod.setChecked(setup['measure_period'])
    if 'measure_duty_cycle' in setup:
        main_window.ui.actionDuty_cycle.setChecked(setup['measure_duty_cycle'])
    if 'measure_pulse_width' in setup:
        main_window.ui.actionPulse_width.setChecked(setup['measure_pulse_width'])
    if 'measure_risetime' in setup:
        main_window.ui.actionRisetime.setChecked(setup['measure_risetime'])
    if 'measure_risetime_error' in setup:
        main_window.ui.actionRisetime_error.setChecked(setup['measure_risetime_error'])
    if 'measure_edge_fit' in setup:
        main_window.ui.actionEdge_fit_method.setChecked(setup['measure_edge_fit'])
    if 'measure_trig_thresh' in setup:
        main_window.ui.actionTrigger_thresh.setChecked(setup['measure_trig_thresh'])
    if 'measure_n_persist' in setup:
        main_window.ui.actionN_persist_lines.setChecked(setup['measure_n_persist'])
    # Handle new separate temperature settings
    if 'measure_adc_temp' in setup:
        main_window.ui.actionADC_temperature.setChecked(setup['measure_adc_temp'])
    elif 'measure_temps' in setup:
        # Backward compatibility: if old setting exists, apply to both
        main_window.ui.actionADC_temperature.setChecked(setup['measure_temps'])
    if 'measure_board_temp' in setup:
        main_window.ui.actionBoard_temperature.setChecked(setup['measure_board_temp'])
    elif 'measure_temps' in setup:
        # Backward compatibility: if old setting exists, apply to both
        main_window.ui.actionBoard_temperature.setChecked(setup['measure_temps'])

    # Active measurements in table
    if 'active_measurements' in setup:
        # Restore active measurements
        main_window.measurements.active_measurements.clear()
        for measurement_name, channel_key in setup['active_measurements']:
            main_window.measurements.active_measurements[(measurement_name, channel_key)] = True

    # Other settings
    if 'high_resolution' in setup:
        main_window.ui.actionHigh_resolution.setChecked(setup['high_resolution'])
        main_window.high_resolution_toggled(setup['high_resolution'])
    else:
        # If high_resolution wasn't saved, still need to send downsample with current highres setting
        if 'downsample' in setup:
            highres = 1 if main_window.ui.actionHigh_resolution.isChecked() else 0
            main_window.controller.tell_downsample_all(s.downsample, highres)
    if 'trig_stabilizer_enabled' in setup:
        s.trig_stabilizer_enabled = setup['trig_stabilizer_enabled']
        main_window.ui.actionToggle_trig_stabilizer.setChecked(s.trig_stabilizer_enabled)
    if 'extra_trig_stabilizer_enabled' in setup:
        s.extra_trig_stabilizer_enabled = setup['extra_trig_stabilizer_enabled']
        main_window.ui.actionToggle_extra_trig_stabilizer.setChecked(s.extra_trig_stabilizer_enabled)
    if 'pulse_stabilizer_enabled' in setup:
        loaded_pulse_stabilizer = setup['pulse_stabilizer_enabled']
        # Handle backward compatibility: convert scalar to array
        if isinstance(loaded_pulse_stabilizer, bool):
            s.pulse_stabilizer_enabled = [loaded_pulse_stabilizer] * s.num_board
        else:
            s.pulse_stabilizer_enabled = loaded_pulse_stabilizer
        main_window.ui.actionPulse_stabilizer.setChecked(s.pulse_stabilizer_enabled[s.activeboard])
    if 'oversampling_controls' in setup:
        main_window.ui.actionOversampling_controls.setChecked(setup['oversampling_controls'])
        # Apply the oversampling controls state
        is_enabled = setup['oversampling_controls']
        main_window.ui.ToffBox.setEnabled(is_enabled)
        main_window.ui.tadBox.setEnabled(is_enabled)
    if 'pll_controls' in setup:
        # Need to set checkbox first, then toggle if needed to match saved state
        current_pll_enabled = main_window.ui.pllBox.isEnabled()
        if current_pll_enabled != setup['pll_controls']:
            main_window.ui.actionToggle_PLL_controls.setChecked(setup['pll_controls'])
            main_window.toggle_pll_controls()
        else:
            main_window.ui.actionToggle_PLL_controls.setChecked(setup['pll_controls'])
    if 'auto_oversample_alignment' in setup:
        main_window.ui.actionAuto_oversample_alignment.setChecked(setup['auto_oversample_alignment'])

    # FIR correction settings
    if 'fir_correction_enabled' in setup:
        s.fir_correction_enabled = setup['fir_correction_enabled']
        main_window.ui.actionApply_FIR_corrections.setChecked(s.fir_correction_enabled)

    # Polynomial filtering settings
    if 'polynomial_filtering_enabled' in setup:
        s.polynomial_filtering_enabled = setup['polynomial_filtering_enabled']
        main_window.ui.actionApply_polynomial_filtering.setChecked(s.polynomial_filtering_enabled)
    if 'savgol_window_length' in setup:
        s.savgol_window_length = setup['savgol_window_length']
    if 'savgol_polyorder' in setup:
        s.savgol_polyorder = setup['savgol_polyorder']

    # Resampling settings
    if 'polyphase_upsampling_enabled' in setup:
        s.polyphase_upsampling_enabled = setup['polyphase_upsampling_enabled']

    # Active board/channel (restore last to trigger UI updates)
    if 'activeboard' in setup:
        s.activeboard = setup['activeboard']
        main_window.ui.boardBox.setCurrentIndex(s.activeboard)
    if 'selectedchannel' in setup:
        s.selectedchannel = setup['selectedchannel']
        main_window.ui.chanBox.setCurrentIndex(s.selectedchannel)

    # Recalculate VperD for all channels based on loaded gain values
    # This MUST be done before syncing to hardware because offset calculation depends on VperD
    if 'gain' in setup:
        for ch_idx in range(s.num_board * s.num_chan_per_board):
            board_idx = ch_idx // s.num_chan_per_board
            db = s.gain[ch_idx]
            v_per_div = (s.basevoltage / 1000.) * s.tenx[ch_idx] / pow(10, db / 20.)
            if s.dooversample[board_idx]:
                v_per_div *= 2.0
            if not s.mohm[ch_idx]:
                v_per_div /= 2.0
            s.VperD[ch_idx] = v_per_div

    # Apply all settings to hardware and update UI
    for board_idx in range(s.num_board):
        main_window._sync_board_settings_to_hardware(board_idx)
        main_window.controller.send_trigger_info(board_idx)
        # Send trigger delay and holdoff if they were restored
        if 'trigger_delay' in setup or 'trigger_holdoff' in setup:
            main_window.controller.send_trigger_delay(board_idx)

    # Update the display
    main_window.select_channel()  # This will update all UI elements
    main_window.allocate_xy_data()
    main_window.time_changed()
    main_window.plot_manager.show_cursors(main_window.ui.actionCursors.isChecked())
    main_window._update_channel_mode_ui()

    # Note: We don't call gain_changed() or offset_changed() here because:
    # 1. VperD has already been recalculated for all channels above
    # 2. _sync_board_settings_to_hardware() has already applied all settings
    # 3. gain_changed() would adjust offsetBox which could reset the loaded offset value

    # Update persistence display after restoring visibility and persistence settings
    main_window.set_average_line_pen()

    # Refresh math window channel list if it exists (channel availability may have changed)
    if main_window.math_window:
        main_window.math_window.update_channel_list()

    # Refresh XY window channel list if visible (channel availability may have changed)
    if main_window.xy_window is not None and main_window.xy_window.isVisible():
        main_window.xy_window.refresh_channel_list()

    # Restore math channels
    if 'math_channels' in setup and len(setup['math_channels']) > 0:
        # Create math window if it doesn't exist
        if main_window.math_window is None:
            main_window.math_window = MathChannelsWindow(main_window)
            main_window.math_window.math_channels_changed.connect(lambda: main_window.update_math_channels())

        # Clear existing math channels
        main_window.math_window.math_channels.clear()
        main_window.math_window.math_list.clear()

        # Restore the math channels list
        main_window.math_window.math_channels = setup['math_channels']

        # Restore the color index counter
        if 'math_channels_next_color_index' in setup:
            main_window.math_window.next_color_index = setup['math_channels_next_color_index']

        # Rebuild the list display
        for math_def in main_window.math_window.math_channels:
            # Use the helper method to create properly formatted display text
            display_text = main_window.math_window.create_math_channel_display_text(math_def)

            item = QListWidgetItem(main_window.math_window.create_color_icon(math_def['color']), display_text)
            main_window.math_window.math_list.addItem(item)

        # Update the plot manager with the math channels
        main_window.plot_manager.update_math_channel_lines(main_window.math_window)

    # Restore custom operations
    if 'custom_operations' in setup and len(setup['custom_operations']) > 0:
        # Create math window if it doesn't exist
        if main_window.math_window is None:
            main_window.math_window = MathChannelsWindow(main_window)
            main_window.math_window.math_channels_changed.connect(lambda: main_window.update_math_channels())

        # Restore custom operations
        main_window.math_window.custom_operations = setup['custom_operations']

        # Repopulate the operations combo box
        main_window.math_window.populate_operations()

    # Restore XY window visibility, geometry, and channel selections
    # This is done AFTER display updates and channel list refreshes to ensure
    # the XY window has the correct available channels
    if 'xy_window_visible' in setup and setup['xy_window_visible']:
        # Show the XY window if it was visible when saved
        if main_window.xy_window is None:
            from xy_window import XYWindow
            main_window.xy_window = XYWindow(main_window, main_window.state, main_window.plot_manager)
            main_window.xy_window.window_closed.connect(main_window.on_xy_window_closed)

        # Restore geometry if available
        if 'xy_window_geometry' in setup:
            geo = setup['xy_window_geometry']
            main_window.xy_window.setGeometry(geo['x'], geo['y'], geo['width'], geo['height'])

        # Restore channel selections if available
        if 'xy_window_y_channel' in setup:
            main_window.xy_window.y_channel = setup['xy_window_y_channel']
            # Find the combo box index for this channel
            for i in range(main_window.xy_window.y_channel_combo.count()):
                if main_window.xy_window.y_channel_combo.itemData(i) == setup['xy_window_y_channel']:
                    main_window.xy_window.y_channel_combo.setCurrentIndex(i)
                    break

        if 'xy_window_x_channel' in setup:
            main_window.xy_window.x_channel = setup['xy_window_x_channel']
            # Find the combo box index for this channel
            for i in range(main_window.xy_window.x_channel_combo.count()):
                if main_window.xy_window.x_channel_combo.itemData(i) == setup['xy_window_x_channel']:
                    main_window.xy_window.x_channel_combo.setCurrentIndex(i)
                    break

        # Show the XY window and update state to match
        main_window.xy_window.show()
        s.xy_mode = True
        main_window.ui.actionXY_Plot.setChecked(True)

    # Restore Zoom window visibility, geometry, and ROI
    if 'zoom_window_visible' in setup and setup['zoom_window_visible']:
        # Show the Zoom window if it was visible when saved
        if main_window.zoom_window is None:
            from zoom_window import ZoomWindow
            main_window.zoom_window = ZoomWindow(main_window, main_window.state, main_window.plot_manager)
            main_window.zoom_window.window_closed.connect(main_window.on_zoom_window_closed)

        # Restore geometry if available
        if 'zoom_window_geometry' in setup:
            geo = setup['zoom_window_geometry']
            main_window.zoom_window.setGeometry(geo['x'], geo['y'], geo['width'], geo['height'])

        # Restore zoom ROI position and size if available
        if 'zoom_roi_geometry' in setup and main_window.plot_manager.zoom_roi is not None:
            roi_geo = setup['zoom_roi_geometry']
            main_window.plot_manager.zoom_roi.setPos([roi_geo['x'], roi_geo['y']])
            main_window.plot_manager.zoom_roi.setSize([roi_geo['width'], roi_geo['height']])

        # Show the zoom window, ROI, and update menu checkbox
        main_window.zoom_window.show()
        main_window.plot_manager.zoom_roi.setVisible(True)
        main_window.ui.actionZoom_window.setChecked(True)
        # Emit initial zoom region to update the zoom window's view range
        main_window.plot_manager.on_zoom_roi_changed()

    # Resume acquisition if it was running
    if not was_paused:
        main_window.dostartstop()

    print(f"Setup loaded from {filename}")
    QMessageBox.information(main_window, "Load Complete", f"Setup loaded from:\n{filename}")
