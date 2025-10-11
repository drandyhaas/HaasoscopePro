# reference_manager.py
"""Manages saving and loading of reference waveforms."""

import numpy as np
from PyQt5.QtWidgets import QMessageBox, QFileDialog


def save_reference_lines(parent, reference_data, reference_visible, math_reference_data=None, math_reference_visible=None):
    """Save all reference waveforms to a file.

    Args:
        parent: Parent widget for dialogs
        reference_data: Dictionary of reference data {channel_idx: {'x_ns': array, 'y': array}}
        reference_visible: Dictionary of visibility states {channel_idx: bool}
        math_reference_data: Dictionary of math channel reference data {math_name: {'x_ns': array, 'y': array}}
        math_reference_visible: Dictionary of math channel visibility states {math_name: bool}
    """
    if not reference_data and not math_reference_data:
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
        save_dict = {}
        channel_indices = []
        math_channel_names = []

        # Save regular channel references with keys like 'ch0_x', 'ch0_y', etc.
        for channel_idx, data in reference_data.items():
            channel_indices.append(channel_idx)
            save_dict[f'ch{channel_idx}_x'] = data['x_ns']
            save_dict[f'ch{channel_idx}_y'] = data['y']
            # Also save visibility state
            save_dict[f'ch{channel_idx}_visible'] = reference_visible.get(channel_idx, True)

        # Save the list of channel indices
        save_dict['channel_indices'] = np.array(channel_indices)

        # Save math channel references with keys like 'math_Math1_x', 'math_Math1_y', etc.
        if math_reference_data:
            for math_name, data in math_reference_data.items():
                math_channel_names.append(math_name)
                save_dict[f'math_{math_name}_x'] = data['x_ns']
                save_dict[f'math_{math_name}_y'] = data['y']
                # Also save visibility state
                if math_reference_visible:
                    save_dict[f'math_{math_name}_visible'] = math_reference_visible.get(math_name, True)

        # Save the list of math channel names
        if math_channel_names:
            save_dict['math_channel_names'] = np.array(math_channel_names, dtype='U')

        # Save to npz file
        np.savez(filename, **save_dict)

        total_count = len(channel_indices) + len(math_channel_names)
        print(f"Reference lines saved to {filename}")
        QMessageBox.information(parent, "Save Successful", f"Saved {total_count} reference line(s) to:\n{filename}")

    except Exception as e:
        QMessageBox.critical(parent, "Save Failed", f"Failed to save reference lines:\n{str(e)}")
        print(f"Error saving reference lines: {e}")


def load_reference_lines(parent, reference_data, reference_visible, math_reference_data=None, math_reference_visible=None):
    """Load reference waveforms from a file.

    Args:
        parent: Parent widget for dialogs
        reference_data: Dictionary to populate with reference data
        reference_visible: Dictionary to populate with visibility states
        math_reference_data: Dictionary to populate with math channel reference data
        math_reference_visible: Dictionary to populate with math channel visibility states

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
        loaded = np.load(filename, allow_pickle=True)

        # Get the list of channel indices (may not exist in older files)
        channel_indices = loaded.get('channel_indices', np.array([]))

        # Clear existing reference data
        reference_data.clear()

        # Load each regular channel's data
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

        # Load math channel references if provided and present in file
        math_count = 0
        if math_reference_data is not None and 'math_channel_names' in loaded:
            # Clear existing math reference data
            math_reference_data.clear()

            math_channel_names = loaded['math_channel_names']
            for math_name in math_channel_names:
                math_name = str(math_name)  # Convert from numpy string
                x_key = f'math_{math_name}_x'
                y_key = f'math_{math_name}_y'
                visible_key = f'math_{math_name}_visible'

                if x_key in loaded and y_key in loaded:
                    math_reference_data[math_name] = {
                        'x_ns': loaded[x_key],
                        'y': loaded[y_key]
                    }
                    math_count += 1

                    # Restore visibility state
                    if math_reference_visible is not None:
                        if visible_key in loaded:
                            math_reference_visible[math_name] = bool(loaded[visible_key])
                        else:
                            math_reference_visible[math_name] = True

        total_count = len(channel_indices) + math_count
        print(f"Reference lines loaded from {filename}")
        QMessageBox.information(parent, "Load Successful", f"Loaded {total_count} reference line(s) from:\n{filename}")

        return True

    except Exception as e:
        QMessageBox.critical(parent, "Load Failed", f"Failed to load reference lines:\n{str(e)}")
        print(f"Error loading reference lines: {e}")
        return False
