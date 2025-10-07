# reference_manager.py
"""Manages saving and loading of reference waveforms."""

import numpy as np
from PyQt5.QtWidgets import QMessageBox, QFileDialog


def save_reference_lines(parent, reference_data, reference_visible):
    """Save all reference waveforms to a file.

    Args:
        parent: Parent widget for dialogs
        reference_data: Dictionary of reference data {channel_idx: {'x_ns': array, 'y': array}}
        reference_visible: Dictionary of visibility states {channel_idx: bool}
    """
    if not reference_data:
        QMessageBox.information(parent, "No References", "No reference waveforms to save.")
        return

    # Open file dialog to choose save location
    filename, _ = QFileDialog.getSaveFileName(
        parent,
        "Save Reference Lines",
        "",
        "NumPy Archive (*.npz);;All Files (*)"
    )

    if not filename:
        return  # User cancelled

    try:
        # Prepare data for saving
        # Save each channel's reference data with keys like 'ch0_x', 'ch0_y', etc.
        save_dict = {}
        channel_indices = []

        for channel_idx, data in reference_data.items():
            channel_indices.append(channel_idx)
            save_dict[f'ch{channel_idx}_x'] = data['x_ns']
            save_dict[f'ch{channel_idx}_y'] = data['y']
            # Also save visibility state
            save_dict[f'ch{channel_idx}_visible'] = reference_visible.get(channel_idx, True)

        # Save the list of channel indices
        save_dict['channel_indices'] = np.array(channel_indices)

        # Save to npz file
        np.savez(filename, **save_dict)

        print(f"Reference lines saved to {filename}")
        QMessageBox.information(parent, "Save Successful", f"Reference lines saved to:\n{filename}")

    except Exception as e:
        QMessageBox.critical(parent, "Save Failed", f"Failed to save reference lines:\n{str(e)}")
        print(f"Error saving reference lines: {e}")


def load_reference_lines(parent, reference_data, reference_visible):
    """Load reference waveforms from a file.

    Args:
        parent: Parent widget for dialogs
        reference_data: Dictionary to populate with reference data
        reference_visible: Dictionary to populate with visibility states

    Returns:
        bool: True if data was loaded successfully, False otherwise
    """
    # Open file dialog to choose file to load
    filename, _ = QFileDialog.getOpenFileName(
        parent,
        "Load Reference Lines",
        "",
        "NumPy Archive (*.npz);;All Files (*)"
    )

    if not filename:
        return False  # User cancelled

    try:
        # Load the npz file
        loaded = np.load(filename)

        # Get the list of channel indices
        if 'channel_indices' not in loaded:
            QMessageBox.critical(parent, "Load Failed", "Invalid reference lines file format.")
            return False

        channel_indices = loaded['channel_indices']

        # Clear existing reference data
        reference_data.clear()

        # Load each channel's data
        for channel_idx in channel_indices:
            channel_idx = int(channel_idx)  # Convert from numpy int
            x_key = f'ch{channel_idx}_x'
            y_key = f'ch{channel_idx}_y'
            visible_key = f'ch{channel_idx}_visible'

            if x_key in loaded and y_key in loaded:
                reference_data[channel_idx] = {
                    'x_ns': loaded[x_key],
                    'y': loaded[y_key]
                }

                # Restore visibility state
                if visible_key in loaded:
                    reference_visible[channel_idx] = bool(loaded[visible_key])
                else:
                    reference_visible[channel_idx] = True

        print(f"Reference lines loaded from {filename}")
        QMessageBox.information(parent, "Load Successful", f"Loaded {len(channel_indices)} reference line(s) from:\n{filename}")

        return True

    except Exception as e:
        QMessageBox.critical(parent, "Load Failed", f"Failed to load reference lines:\n{str(e)}")
        print(f"Error loading reference lines: {e}")
        return False
