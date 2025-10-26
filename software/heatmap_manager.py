"""
Heatmap Manager for HaasoscopePro
Handles persist line heatmap visualization
"""

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore


class HeatmapManager:
    """Manages heatmap visualization for persist lines."""

    def __init__(self, plot, state):
        """
        Initialize the HeatmapManager.

        Args:
            plot: The PlotItem where heatmaps will be displayed
            state: The ScopeState object containing application state
        """
        self.plot = plot
        self.state = state

        # Heatmap attributes (per-channel)
        self.persist_heatmap_data = {}  # Dictionary: {channel_index: 2D numpy array}
        self.persist_heatmap_items = {}  # Dictionary: {channel_index: ImageItem}
        self.persist_heatmap_ranges = {}  # Dictionary: {channel_index: ((x_min, x_max), (y_min, y_max))}
        self.persist_heatmap_zoom = {}  # Dictionary: {channel_index: last zoom level when heatmap was created}
        self.persist_heatmap_yscale = {}  # Dictionary: {channel_index: last yscale when heatmap was created}
        self.persist_heatmap_offset = {}  # Dictionary: {channel_index: last offset when heatmap was created}

        # Bin configuration - reduced by 2x for better performance
        self.heatmap_bins_y = 200   # Number of bins in y-direction (voltage)
        self._base_heatmap_bins_x = 1000  # Base number of bins in x-direction (time) at downsample=0

    def get_heatmap_bins_x(self):
        """
        Get the number of x bins.
        Keep constant regardless of zoom to avoid sparsity when zoomed in.
        """
        return self._base_heatmap_bins_x

    def _init_heatmap_for_channel(self, line_idx):
        """Initialize heatmap data structures for a channel."""
        if line_idx in self.persist_heatmap_data:
            return

        # Create 2D histogram initialized to zeros
        # Array shape: (height, width) = (y_bins, x_bins) = (rows, cols)
        bins_x = self.get_heatmap_bins_x()
        self.persist_heatmap_data[line_idx] = np.zeros((self.heatmap_bins_y, bins_x))

        # Store the current zoom level and gain/offset
        self.persist_heatmap_zoom[line_idx] = self.state.downsamplezoom
        self.persist_heatmap_yscale[line_idx] = self.state.yscale
        self.persist_heatmap_offset[line_idx] = self.state.offset

        # Use view range for x (time) and state range for y (voltage)
        # This gives high resolution in the visible area when zoomed
        view_range = self.plot.getViewBox().viewRange()
        view_min_x, view_max_x = view_range[0]

        self.persist_heatmap_ranges[line_idx] = (
            (view_min_x, view_max_x),  # X from current view
            (self.state.min_y, self.state.max_y)  # Y from state (gain/offset)
        )

        # Create ImageItem for rendering
        image_item = pg.ImageItem()
        self.persist_heatmap_items[line_idx] = image_item
        self.plot.addItem(image_item)

        # Set the colormap (blue to red)
        colors = [
            (0, 0, 0, 0),      # transparent (no data)
            (0, 0, 128),       # dark blue (few lines)
            (0, 0, 255),       # blue
            (0, 128, 255),     # cyan
            (0, 255, 128),     # cyan-green
            (0, 255, 0),       # green
            (128, 255, 0),     # yellow-green
            (255, 255, 0),     # yellow
            (255, 128, 0),     # orange
            (255, 0, 0),       # red (many lines)
        ]
        colormap = pg.ColorMap(
            pos=np.linspace(0.0, 1.0, len(colors)),
            color=colors
        )
        image_item.setLookupTable(colormap.getLookupTable())

    def _calculate_heatmap_ranges(self, line_idx, persist_lines):
        """
        Calculate the x and y ranges for the heatmap from the actual persist line data.

        Args:
            line_idx: Channel index
            persist_lines: List of persist line tuples (item, timestamp, line_idx, x_data, y_data)

        Returns:
            Tuple of ((x_min, x_max), (y_min, y_max))
        """
        # Use the actual data range from persist lines, not the view range
        # This ensures heatmap works correctly when zoomed
        if not persist_lines or len(persist_lines) == 0:
            # Fallback to state ranges
            return (self.state.min_x, self.state.max_x), (self.state.min_y, self.state.max_y)

        # Find the overall min/max across ALL persist lines for this channel
        x_min = None
        x_max = None
        y_min = None
        y_max = None

        for item, _, _, x_data, y_data in persist_lines:
            if x_data is not None and len(x_data) > 0:
                x_data_min = np.min(x_data)
                x_data_max = np.max(x_data)
                if x_min is None or x_data_min < x_min:
                    x_min = x_data_min
                if x_max is None or x_data_max > x_max:
                    x_max = x_data_max

            if y_data is not None and len(y_data) > 0:
                y_data_min = np.min(y_data)
                y_data_max = np.max(y_data)
                if y_min is None or y_data_min < y_min:
                    y_min = y_data_min
                if y_max is None or y_data_max > y_max:
                    y_max = y_data_max

        # Use calculated ranges or fallback to state ranges
        if x_min is not None and x_max is not None:
            x_range = (x_min, x_max)
        else:
            x_range = (self.state.min_x, self.state.max_x)

        if y_min is not None and y_max is not None:
            y_range = (y_min, y_max)
        else:
            y_range = (self.state.min_y, self.state.max_y)

        # Store the calculated ranges for consistent use
        self.persist_heatmap_ranges[line_idx] = (x_range, y_range)

        return x_range, y_range

    def _get_heatmap_ranges(self, line_idx):
        """Get the stored heatmap ranges."""
        if line_idx not in self.persist_heatmap_ranges:
            return (self.state.min_x, self.state.max_x), (self.state.min_y, self.state.max_y)
        return self.persist_heatmap_ranges[line_idx]

    def check_zoom_changed(self, line_idx):
        """
        Check if zoom level has changed since heatmap was created.

        Args:
            line_idx: Channel index

        Returns:
            True if zoom level changed, False otherwise
        """
        if line_idx not in self.persist_heatmap_zoom:
            return False

        return self.persist_heatmap_zoom[line_idx] != self.state.downsamplezoom

    def check_view_changed(self, line_idx, threshold=0.1):
        """
        Check if the view range has changed significantly since heatmap was created.

        Args:
            line_idx: Channel index
            threshold: Fraction of range change to trigger regeneration (default 0.1 = 10%)

        Returns:
            True if view range changed significantly, False otherwise
        """
        if line_idx not in self.persist_heatmap_ranges:
            return False

        # Get current and stored view ranges
        view_range = self.plot.getViewBox().viewRange()
        current_min_x, current_max_x = view_range[0]
        (stored_min_x, stored_max_x), _ = self.persist_heatmap_ranges[line_idx]

        # Calculate the range width
        stored_width = stored_max_x - stored_min_x
        if stored_width == 0:
            return True

        # Check if the view has shifted or changed size significantly
        shift = abs((current_min_x + current_max_x) / 2 - (stored_min_x + stored_max_x) / 2)
        size_change = abs((current_max_x - current_min_x) - stored_width)

        # Trigger regeneration if shift or size change exceeds threshold
        return (shift > stored_width * threshold) or (size_change > stored_width * threshold)

    def check_gain_offset_changed(self, line_idx):
        """
        Check if gain (yscale) or offset has changed since heatmap was created.

        Args:
            line_idx: Channel index

        Returns:
            True if gain or offset changed, False otherwise
        """
        if line_idx not in self.persist_heatmap_yscale or line_idx not in self.persist_heatmap_offset:
            return False

        yscale_changed = self.persist_heatmap_yscale[line_idx] != self.state.yscale
        offset_changed = self.persist_heatmap_offset[line_idx] != self.state.offset

        return yscale_changed or offset_changed

    def clear_for_settings_change(self, line_idx):
        """
        Clear heatmap completely when settings change (gain/offset/zoom).
        Does NOT regenerate - lets new traces build it naturally.

        Args:
            line_idx: Channel index
        """
        # Completely remove the ImageItem from the plot
        if line_idx in self.persist_heatmap_items:
            image_item = self.persist_heatmap_items[line_idx]
            image_item.setVisible(False)
            self.plot.removeItem(image_item)
            image_item.clear()
            del self.persist_heatmap_items[line_idx]

        # Remove all stored data
        if line_idx in self.persist_heatmap_data:
            del self.persist_heatmap_data[line_idx]

        if line_idx in self.persist_heatmap_ranges:
            del self.persist_heatmap_ranges[line_idx]

        if line_idx in self.persist_heatmap_zoom:
            del self.persist_heatmap_zoom[line_idx]

        if line_idx in self.persist_heatmap_yscale:
            del self.persist_heatmap_yscale[line_idx]

        if line_idx in self.persist_heatmap_offset:
            del self.persist_heatmap_offset[line_idx]

        # Force a plot update
        self.plot.update()

    def reset_and_regenerate(self, line_idx, persist_lines):
        """
        Fully reset heatmap (like turning checkbox off and on) and regenerate.
        Used when gain/offset/zoom changes require complete rebuild.

        Args:
            line_idx: Channel index
            persist_lines: List of persist line tuples for regeneration
        """
        # Completely remove the ImageItem from the plot first
        if line_idx in self.persist_heatmap_items:
            image_item = self.persist_heatmap_items[line_idx]
            image_item.setVisible(False)
            self.plot.removeItem(image_item)
            # Force the item to be cleared
            image_item.clear()
            del self.persist_heatmap_items[line_idx]

        # Remove all stored data
        if line_idx in self.persist_heatmap_data:
            del self.persist_heatmap_data[line_idx]

        if line_idx in self.persist_heatmap_ranges:
            del self.persist_heatmap_ranges[line_idx]

        if line_idx in self.persist_heatmap_zoom:
            del self.persist_heatmap_zoom[line_idx]

        if line_idx in self.persist_heatmap_yscale:
            del self.persist_heatmap_yscale[line_idx]

        if line_idx in self.persist_heatmap_offset:
            del self.persist_heatmap_offset[line_idx]

        # Force a plot update to ensure the old item is removed
        self.plot.update()

        # Now regenerate from scratch (like turning checkbox back on)
        # This will create a completely new ImageItem
        self.regenerate(line_idx, persist_lines)

    def add_trace(self, x, y, line_idx, persist_lines=None):
        """
        Add a trace to the heatmap for a specific channel.

        Args:
            x: x-coordinate data (time)
            y: y-coordinate data (voltage)
            line_idx: Channel index
            persist_lines: Optional list of all persist lines (for regeneration if settings changed)
        """
        self._init_heatmap_for_channel(line_idx)

        heatmap = self.persist_heatmap_data[line_idx]
        (x_min, x_max), (y_min, y_max) = self._get_heatmap_ranges(line_idx)

        # Filter to only data within the heatmap's range
        mask = (x >= x_min) & (x <= x_max)
        if not np.any(mask):
            # No data in heatmap range, skip
            return

        x_filtered = x[mask]
        y_filtered = y[mask]

        # Get bins from actual array dimensions
        bins_y, bins_x = heatmap.shape

        # Convert x, y data to bin indices
        # x (time) should map to columns (x_bins)
        # y (voltage) should map to rows (y_bins)
        x_bins = np.clip(
            ((x_filtered - x_min) / (x_max - x_min) * bins_x).astype(int),
            0, bins_x - 1
        )
        y_bins = np.clip(
            ((y_filtered - y_min) / (y_max - y_min) * bins_y).astype(int),
            0, bins_y - 1
        )

        # Accumulate into the heatmap
        # Array is [rows, cols] = [y_bins, x_bins] = [voltage, time]
        for xb, yb in zip(x_bins, y_bins):
            if 0 <= xb < bins_x and 0 <= yb < bins_y:
                heatmap[yb, xb] += 1

        self.update_image(line_idx)

    def remove_trace(self, x, y, line_idx):
        """
        Remove a trace from the heatmap for a specific channel.

        Args:
            x: x-coordinate data (time)
            y: y-coordinate data (voltage)
            line_idx: Channel index
        """
        if line_idx not in self.persist_heatmap_data:
            return

        heatmap = self.persist_heatmap_data[line_idx]
        (x_min, x_max), (y_min, y_max) = self._get_heatmap_ranges(line_idx)

        # Filter to only data within the heatmap's range
        mask = (x >= x_min) & (x <= x_max)
        if not np.any(mask):
            # No data in heatmap range, skip
            return

        x_filtered = x[mask]
        y_filtered = y[mask]

        # Get bins from actual array dimensions
        bins_y, bins_x = heatmap.shape

        # Convert x, y data to bin indices (same as add_trace)
        x_bins = np.clip(
            ((x_filtered - x_min) / (x_max - x_min) * bins_x).astype(int),
            0, bins_x - 1
        )
        y_bins = np.clip(
            ((y_filtered - y_min) / (y_max - y_min) * bins_y).astype(int),
            0, bins_y - 1
        )

        # Subtract from the heatmap (don't go below 0)
        for xb, yb in zip(x_bins, y_bins):
            if 0 <= xb < bins_x and 0 <= yb < bins_y:
                heatmap[yb, xb] = max(0, heatmap[yb, xb] - 1)

        self.update_image(line_idx)

    def update_image(self, line_idx):
        """
        Update the heatmap image display.

        Args:
            line_idx: Channel index
        """
        if line_idx not in self.persist_heatmap_items:
            return

        heatmap = self.persist_heatmap_data[line_idx]
        image_item = self.persist_heatmap_items[line_idx]

        # Get non-zero values for better color scaling
        nonzero_values = heatmap[heatmap > 0]

        if len(nonzero_values) == 0:
            # No data - use default scaling
            min_level = 0
            max_level = 1
        else:
            # Use percentile-based scaling for balanced color distribution
            # This ensures we see the full color range (blue to red) in the data
            min_level = 0
            # Use 90th percentile instead of max to avoid outliers dominating the scale
            max_level = np.percentile(nonzero_values, 90)
            # Ensure max_level is at least 1
            max_level = max(max_level, 1)

        # PyQtGraph default: array[i,j] where i is treated as x (horizontal) and j as y (vertical)
        # Our array is (y_bins, x_bins), so we need to transpose to (x_bins, y_bins)
        # PyQtGraph puts j=0 at the bottom by default, which matches y_bin=0 = y_min
        heatmap_display = heatmap.T  # Transpose to (x_bins, y_bins)

        # Update the image with percentile-based color scaling
        # This distributes colors more evenly - blues for lower counts, reds for higher counts
        image_item.setImage(heatmap_display, levels=(min_level, max_level))

        # Set the position and scale to match the plot coordinates
        (x_min, x_max), (y_min, y_max) = self._get_heatmap_ranges(line_idx)
        image_item.setRect(pg.QtCore.QRectF(x_min, y_min, x_max - x_min, y_max - y_min))

        # Ensure visibility is set correctly
        image_item.setVisible(self.state.persist_heatmap_enabled[line_idx] and self.state.persist_time[line_idx] > 0)

    def regenerate(self, line_idx, persist_lines):
        """
        Regenerate the heatmap from all current persist lines for a specific channel.
        Used when zoom level changes or ranges need to be recalculated.

        Args:
            line_idx: Channel index
            persist_lines: List of persist line tuples (item, timestamp, line_idx, x_data, y_data)
        """
        self._init_heatmap_for_channel(line_idx)

        # Update ranges to current view (for x) and state (for y)
        view_range = self.plot.getViewBox().viewRange()
        view_min_x, view_max_x = view_range[0]

        self.persist_heatmap_ranges[line_idx] = (
            (view_min_x, view_max_x),  # X from current view
            (self.state.min_y, self.state.max_y)  # Y from state (gain/offset)
        )

        # Recreate heatmap with potentially different x bin count
        bins_x = self.get_heatmap_bins_x()
        self.persist_heatmap_data[line_idx] = np.zeros((self.heatmap_bins_y, bins_x))
        heatmap = self.persist_heatmap_data[line_idx]

        # Update stored zoom level and gain/offset
        self.persist_heatmap_zoom[line_idx] = self.state.downsamplezoom
        self.persist_heatmap_yscale[line_idx] = self.state.yscale
        self.persist_heatmap_offset[line_idx] = self.state.offset

        if not persist_lines or len(persist_lines) == 0:
            self.update_image(line_idx)
            return

        # Get ranges
        (x_min, x_max), (y_min, y_max) = self._get_heatmap_ranges(line_idx)

        # Accumulate all persist lines into the heatmap
        for item, _, _, x, y in persist_lines:
            if x is None or y is None or len(x) == 0:
                continue

            # Filter to only data within the heatmap's range
            mask = (x >= x_min) & (x <= x_max)
            if not np.any(mask):
                continue

            x_filtered = x[mask]
            y_filtered = y[mask]

            # Convert x, y data to bin indices
            x_bins = np.clip(
                ((x_filtered - x_min) / (x_max - x_min) * bins_x).astype(int),
                0, bins_x - 1
            )
            y_bins = np.clip(
                ((y_filtered - y_min) / (y_max - y_min) * self.heatmap_bins_y).astype(int),
                0, self.heatmap_bins_y - 1
            )

            # Accumulate into the heatmap
            for xb, yb in zip(x_bins, y_bins):
                if 0 <= xb < bins_x and 0 <= yb < self.heatmap_bins_y:
                    heatmap[yb, xb] += 1

        # Update the image once after all traces are added
        self.update_image(line_idx)

    def clear_channel(self, line_idx):
        """
        Clear heatmap data for a specific channel.

        Args:
            line_idx: Channel index
        """
        if line_idx in self.persist_heatmap_data:
            self.persist_heatmap_data[line_idx].fill(0)
            self.update_image(line_idx)

    def remove_channel(self, line_idx):
        """
        Remove all heatmap data and items for a specific channel.

        Args:
            line_idx: Channel index
        """
        if line_idx in self.persist_heatmap_items:
            self.plot.removeItem(self.persist_heatmap_items[line_idx])
            del self.persist_heatmap_items[line_idx]

        if line_idx in self.persist_heatmap_data:
            del self.persist_heatmap_data[line_idx]

        if line_idx in self.persist_heatmap_ranges:
            del self.persist_heatmap_ranges[line_idx]

        if line_idx in self.persist_heatmap_zoom:
            del self.persist_heatmap_zoom[line_idx]

        if line_idx in self.persist_heatmap_yscale:
            del self.persist_heatmap_yscale[line_idx]

        if line_idx in self.persist_heatmap_offset:
            del self.persist_heatmap_offset[line_idx]
