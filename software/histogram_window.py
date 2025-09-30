# histogram_window.py

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets
from PyQt5.QtGui import QColor


class HistogramWindow(QtWidgets.QWidget):
    """Popup window showing a histogram of measurement values."""
    
    def __init__(self, parent=None, plot_manager=None):
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.plot_manager = plot_manager
        
        # Setup layout
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Create plot widget
        self.plot_widget = pg.PlotWidget()
        
        # Match styling to main plot
        self.plot_widget.setBackground(QColor('black'))
        self.plot_widget.showGrid(x=True, y=True, alpha=0.8)
        
        # Set font and styling to match main plot
        font = QtWidgets.QApplication.font()
        font.setPixelSize(11)

        for axis in ['bottom', 'left']:
            axis_item = self.plot_widget.getAxis(axis)
            axis_item.setStyle(tickFont=font)
            self.plot_widget.getAxis(axis).setPen('grey')
            self.plot_widget.getAxis(axis).setTextPen('grey')

        # Set title font
        self.plot_widget.getPlotItem().titleLabel.item.setFont(font)

        # Disable mouse interactions
        self.plot_widget.setMouseEnabled(x=False, y=False)
        self.plot_widget.setMenuEnabled(False)

        self.plot_widget.setLabel('left', 'Count')
        self.plot_widget.setLabel('bottom', 'Value')

        layout.addWidget(self.plot_widget)
        self.setLayout(layout)

        self.bar_graph = None

    def update_histogram(self, measurement_name, values, brush_color=None):
        """Update the histogram with new data."""
        if len(values) == 0:
            return

        # Calculate histogram
        y, x = np.histogram(list(values), bins=20)

        # Use provided color or default to blue
        if brush_color is None:
            brush_color = 'b'

        # Create bar graph if it doesn't exist
        if self.bar_graph is None:
            self.bar_graph = pg.BarGraphItem(x=x[:-1], height=y, width=(x[1]-x[0])*0.8, brush=brush_color)
            self.plot_widget.addItem(self.bar_graph)
        else:
            self.bar_graph.setOpts(x=x[:-1], height=y, width=(x[1]-x[0])*0.8, brush=brush_color)

        # Update title and axis
        self.plot_widget.setTitle(f'{measurement_name} Distribution (n={len(values)})', color='grey')

    def position_relative_to_table(self, table_widget, main_plot_widget):
        """Position the window to the left of the measurement table, with bottom aligned to main plot."""
        # Get table geometry in global coordinates
        table_global_pos = table_widget.mapToGlobal(table_widget.pos())
        table_rect = table_widget.geometry()

        # Get main plot bottom position
        plot_global_pos = main_plot_widget.mapToGlobal(main_plot_widget.pos())
        plot_rect = main_plot_widget.geometry()
        plot_bottom = plot_global_pos.y() + plot_rect.height()

        # Position to the left of table, with same width and bottom aligned to plot
        heightcorr = 0
        if table_rect.height() > 300:
            heightcorr = table_rect.height() - 300
        self.setGeometry(table_global_pos.x() - table_rect.width() - 2,
                        plot_bottom - table_rect.height() - 8 + heightcorr,
                        table_rect.width(),
                        table_rect.height() - heightcorr)
