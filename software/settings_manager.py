# settings_manager.py
"""Handles saving and loading scope setup configurations to/from JSON files."""

import json
from PyQt5.QtWidgets import QMessageBox, QFileDialog
from PyQt5.QtGui import QColor


def save_setup(main_window):
    """Save current scope setup to a JSON file.

    Args:
        main_window: The MainWindow instance containing all scope state
    """
    filename, _ = QFileDialog.getSaveFileName(
        main_window, "Save Setup", "", "JSON Files (*.json);;All Files (*)"
    )
    if not filename:
        return

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
        'triggerpos': s.triggerpos,
        'triggerchan': s.triggerchan,
        'fallingedge': s.fallingedge,
        'triggertype': s.triggertype,
        'triggertimethresh': s.triggertimethresh,
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

        # Processing settings
        'doresamp': s.doresamp,
        'fitwidthfraction': s.fitwidthfraction,

        # FFT and reference settings
        'fft_enabled': s.fft_enabled,
        'reference_visible': main_window.reference_visible,

        # Plot manager settings
        'line_width': main_window.ui.linewidthBox.value(),
        'persistence': main_window.ui.persistTbox.value(),
        'persist_avg_enabled': main_window.ui.persistavgCheck.isChecked(),
        'persist_lines_enabled': main_window.ui.persistlinesCheck.isChecked(),

        # Channel visibility (per-channel)
        'channel_visible': [line.isVisible() for line in main_window.plot_manager.lines],

        # Channel colors
        'channel_colors': [pen.color().name() for pen in main_window.plot_manager.linepens],

        # View menu states
        'grid_visible': main_window.ui.actionGrid.isChecked(),
        'markers_visible': main_window.ui.actionMarkers.isChecked(),
        'voltage_axis_visible': main_window.ui.actionVoltage_axis.isChecked(),
        'pan_and_zoom': main_window.ui.actionPan_and_zoom.isChecked(),

        # Measurement menu states
        'measure_mean': main_window.ui.actionMean.isChecked(),
        'measure_rms': main_window.ui.actionRMS.isChecked(),
        'measure_min': main_window.ui.actionMinimum.isChecked(),
        'measure_max': main_window.ui.actionMaximum.isChecked(),
        'measure_vpp': main_window.ui.actionVpp.isChecked(),
        'measure_freq': main_window.ui.actionFreq.isChecked(),
        'measure_risetime': main_window.ui.actionRisetime.isChecked(),
        'measure_risetime_error': main_window.ui.actionRisetime_error.isChecked(),
        'measure_edge_fit': main_window.ui.actionEdge_fit_method.isChecked(),
        'measure_trig_thresh': main_window.ui.actionTrigger_thresh.isChecked(),
        'measure_n_persist': main_window.ui.actionN_persist_lines.isChecked(),
        'measure_temps': main_window.ui.actionTemperatures.isChecked(),

        # Other settings
        'high_resolution': main_window.ui.actionHigh_resolution.isChecked(),
        'trig_stabilizer_enabled': s.trig_stabilizer_enabled,
        'extra_trig_stabilizer_enabled': s.extra_trig_stabilizer_enabled,
    }

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
    filename, _ = QFileDialog.getOpenFileName(
        main_window, "Load Setup", "", "JSON Files (*.json);;All Files (*)"
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

    # Restore state variables
    # Timebase and acquisition
    if 'downsample' in setup:
        s.downsample = setup['downsample']
        main_window.controller.tell_downsample_all(s.downsample)
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
        main_window.ui.thresholdDelta.setValue(s.triggerdelta)
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
    if 'triggertimethresh' in setup:
        s.triggertimethresh = setup['triggertimethresh']
        main_window.ui.totBox.setValue(s.triggertimethresh)
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

    # Board mode settings
    if 'dotwochannel' in setup:
        s.dotwochannel = setup['dotwochannel']
    if 'dooversample' in setup:
        s.dooversample = setup['dooversample']
    if 'dointerleaved' in setup:
        s.dointerleaved = setup['dointerleaved']

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
    if 'xy_mode' in setup and setup['xy_mode']:
        # Restore XY mode if it was enabled
        if s.dotwochannel[s.activeboard]:
            main_window.ui.actionXY_Plot.setChecked(True)
            main_window.plot_manager.toggle_xy_view(True, s.activeboard)

    # Processing settings
    if 'doresamp' in setup:
        s.doresamp = setup['doresamp']
        main_window.ui.resampBox.setValue(s.doresamp)
    if 'fitwidthfraction' in setup:
        s.fitwidthfraction = setup['fitwidthfraction']
        main_window.ui.fwfBox.setValue(int(s.fitwidthfraction * 100))

    # FFT and reference settings
    if 'fft_enabled' in setup:
        s.fft_enabled = setup['fft_enabled']
    if 'reference_visible' in setup:
        # Convert string keys to integers
        main_window.reference_visible = {int(k): v for k, v in setup['reference_visible'].items()}

    # Plot manager settings
    if 'line_width' in setup:
        main_window.ui.linewidthBox.setValue(setup['line_width'])
    if 'persistence' in setup:
        main_window.ui.persistTbox.setValue(setup['persistence'])
    if 'persist_avg_enabled' in setup:
        main_window.ui.persistavgCheck.setChecked(setup['persist_avg_enabled'])
    if 'persist_lines_enabled' in setup:
        main_window.ui.persistlinesCheck.setChecked(setup['persist_lines_enabled'])

    # Channel visibility (per-channel)
    if 'channel_visible' in setup:
        for idx, is_visible in enumerate(setup['channel_visible']):
            if idx < len(main_window.plot_manager.lines):
                main_window.plot_manager.lines[idx].setVisible(is_visible)

    # Channel colors
    if 'channel_colors' in setup:
        for idx, color_name in enumerate(setup['channel_colors']):
            if idx < len(main_window.plot_manager.linepens):
                main_window.plot_manager.linepens[idx].setColor(QColor(color_name))

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
    if 'measure_temps' in setup:
        main_window.ui.actionTemperatures.setChecked(setup['measure_temps'])

    # Other settings
    if 'high_resolution' in setup:
        main_window.ui.actionHigh_resolution.setChecked(setup['high_resolution'])
        s.highresval = 1 if setup['high_resolution'] else 0
    if 'trig_stabilizer_enabled' in setup:
        s.trig_stabilizer_enabled = setup['trig_stabilizer_enabled']
        main_window.ui.actionToggle_trig_stabilizer.setChecked(s.trig_stabilizer_enabled)
    if 'extra_trig_stabilizer_enabled' in setup:
        s.extra_trig_stabilizer_enabled = setup['extra_trig_stabilizer_enabled']
        main_window.ui.actionToggle_extra_trig_stabilizer.setChecked(s.extra_trig_stabilizer_enabled)

    # Active board/channel (restore last to trigger UI updates)
    if 'activeboard' in setup:
        s.activeboard = setup['activeboard']
        main_window.ui.boardBox.setValue(s.activeboard)
    if 'selectedchannel' in setup:
        s.selectedchannel = setup['selectedchannel']
        main_window.ui.chanBox.setValue(s.selectedchannel)

    # Apply all settings to hardware and update UI
    for board_idx in range(s.num_board):
        main_window._sync_board_settings_to_hardware(board_idx)
        main_window.controller.send_trigger_info(board_idx)

    # Update the display
    main_window.select_channel()  # This will update all UI elements
    main_window.allocate_xy_data()
    main_window.time_changed()
    main_window._update_channel_mode_ui()

    # Update persistence display after restoring visibility and persistence settings
    main_window.set_average_line_pen()

    # Resume acquisition if it was running
    if not was_paused:
        main_window.dostartstop()

    print(f"Setup loaded from {filename}")
    QMessageBox.information(main_window, "Load Complete", f"Setup loaded from:\n{filename}")
