# fft_processor.py

from concurrent.futures import ThreadPoolExecutor
import numpy as np


class FFTProcessor:
    """Handles asynchronous FFT calculations using a thread pool."""

    def __init__(self, max_workers=2):
        """
        Initialize the FFT processor with a thread pool.

        Args:
            max_workers: Maximum number of worker threads for FFT calculations
        """
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.pending_ffts = {}  # Track pending computations by channel name
        self.last_results = {}  # Cache last successful results

    def submit_fft_calculation(self, channel_name, y_data, board_idx, state):
        """
        Submit an FFT calculation to the thread pool (non-blocking).

        Args:
            channel_name: Unique identifier for the channel (e.g., "CH1", "MATH1")
            y_data: Input signal data array
            board_idx: Board index for this channel
            state: Application state object containing configuration

        Returns:
            Future object representing the pending calculation
        """
        # Cancel any pending FFT for this channel to avoid queue buildup
        if channel_name in self.pending_ffts:
            future = self.pending_ffts[channel_name]
            if not future.done():
                future.cancel()

        # Submit new FFT calculation with copied data to avoid race conditions
        future = self.executor.submit(
            self._calculate_fft_worker,
            y_data.copy(),  # Copy to ensure thread safety
            board_idx,
            state.dotwochannel[board_idx] if board_idx < len(state.dotwochannel) else False,
            state.dointerleaved[board_idx] if board_idx < len(state.dointerleaved) else False,
            state.downsamplefactor,
            state.samplerate
        )
        self.pending_ffts[channel_name] = future
        return future

    @staticmethod
    def _calculate_fft_worker(y_data, board_idx, dotwochannel, dointerleaved,
                              downsamplefactor, samplerate):
        """
        Worker function that runs in a background thread.
        This is a thread-safe version of DataProcessor.calculate_fft().

        Args:
            y_data: Input signal data
            board_idx: Board index
            dotwochannel: Whether board is in two-channel mode
            dointerleaved: Whether board is in interleaved mode
            downsamplefactor: Downsampling factor
            samplerate: Sample rate in GS/s

        Returns:
            Tuple of (freq_array, magnitude_array)
        """
        n = len(y_data)
        if n < 2:
            return np.array([]), np.array([])

        k = np.arange(n)

        # Calculate microseconds per sample based on board configuration
        uspersample = downsamplefactor / samplerate / 1000.
        if dointerleaved:
            uspersample /= 2
        elif dotwochannel:
            uspersample *= 2

        # Compute FFT and frequency array
        freq = (k / uspersample)[list(range(n // 2))] / n
        Y = np.fft.fft(y_data)[list(range(n // 2))] / n
        Y[0] = 1e-3  # Suppress DC component for better plotting

        return freq, np.abs(Y)

    def get_fft_result(self, channel_name, use_cached=True, timeout=None):
        """
        Retrieve FFT result if ready (non-blocking by default).

        Args:
            channel_name: Channel identifier
            use_cached: If True, return last successful result if current is not ready
            timeout: If specified, wait up to this many seconds for result (blocking)

        Returns:
            Tuple of (freq, magnitude) arrays if ready, or cached result, or None
        """
        if channel_name not in self.pending_ffts:
            # No pending calculation, return cached if available
            if use_cached and channel_name in self.last_results:
                return self.last_results[channel_name]
            return None

        future = self.pending_ffts[channel_name]

        # Check if the calculation is complete (or wait if timeout specified)
        try:
            # If timeout is specified, wait for result (blocking)
            # If timeout is None, just check if done (non-blocking)
            if timeout is not None:
                result = future.result(timeout=timeout)
            elif future.done():
                result = future.result(timeout=0)
            else:
                # Not done yet and no timeout specified
                # Return cached result if available
                if use_cached and channel_name in self.last_results:
                    return self.last_results[channel_name]
                return None

            # Cache the successful result
            self.last_results[channel_name] = result
            # Clean up the future
            del self.pending_ffts[channel_name]
            return result
        except Exception as e:
            # On timeout or error
            if timeout is not None:
                # Timeout occurred, calculation still pending
                if use_cached and channel_name in self.last_results:
                    return self.last_results[channel_name]
                return None
            else:
                # Actual error
                print(f"FFT calculation error for {channel_name}: {e}")
                if channel_name in self.pending_ffts:
                    del self.pending_ffts[channel_name]
                # Return cached result on error if available
                if use_cached and channel_name in self.last_results:
                    return self.last_results[channel_name]
                return None

    def clear_channel_cache(self, channel_name):
        """Clear cached FFT result for a specific channel."""
        if channel_name in self.last_results:
            del self.last_results[channel_name]
        if channel_name in self.pending_ffts:
            future = self.pending_ffts[channel_name]
            if not future.done():
                future.cancel()
            del self.pending_ffts[channel_name]

    def clear_all_caches(self):
        """Clear all cached FFT results and cancel pending calculations."""
        for future in self.pending_ffts.values():
            if not future.done():
                future.cancel()
        self.pending_ffts.clear()
        self.last_results.clear()

    def cleanup(self):
        """Shutdown the thread pool. Call this on application exit."""
        # Cancel all pending futures
        for future in self.pending_ffts.values():
            if not future.done():
                future.cancel()
        # Shutdown the executor
        self.executor.shutdown(wait=False)
        self.pending_ffts.clear()
        self.last_results.clear()
