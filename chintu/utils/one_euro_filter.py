"""
One Euro Filter implementation for smoothing noisy signals.
Used to stabilize hand landmark positions from MediaPipe.

Based on: http://cristal.univ-lille.fr/~casiez/1euro/
"""

import math
from typing import Optional
import time


class LowPassFilter:
    """Simple low-pass filter."""
    
    def __init__(self, alpha: float = 1.0):
        self._alpha = alpha
        self._y: Optional[float] = None
        self._s: Optional[float] = None
    
    def set_alpha(self, alpha: float):
        """Set the smoothing factor (0 < alpha <= 1)."""
        self._alpha = max(0.0, min(1.0, alpha))
    
    def filter(self, value: float) -> float:
        """Apply the low-pass filter."""
        if self._y is None:
            self._s = value
        else:
            self._s = self._alpha * value + (1.0 - self._alpha) * self._s
        self._y = value
        return self._s
    
    def has_last_raw_value(self) -> bool:
        return self._y is not None
    
    def last_raw_value(self) -> float:
        return self._y if self._y is not None else 0.0


class OneEuroFilter:
    """
    One Euro Filter for adaptive low-pass filtering.
    
    Good for smoothing noisy signals like hand tracking landmarks
    while maintaining responsiveness to quick movements.
    
    Parameters:
        freq: Sampling frequency (Hz)
        min_cutoff: Minimum cutoff frequency (Hz). Lower = more smoothing
        beta: Speed coefficient. Higher = less lag during fast movements
        d_cutoff: Derivative cutoff frequency
    """
    
    def __init__(
        self,
        freq: float = 30.0,
        min_cutoff: float = 1.0,
        beta: float = 0.007,
        d_cutoff: float = 1.0,
    ):
        self._freq = freq
        self._min_cutoff = min_cutoff
        self._beta = beta
        self._d_cutoff = d_cutoff
        
        self._x = LowPassFilter()
        self._dx = LowPassFilter()
        self._last_time: Optional[float] = None
    
    def _alpha(self, cutoff: float) -> float:
        """Compute alpha based on cutoff frequency."""
        te = 1.0 / self._freq
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / te)
    
    def filter(self, x: float, timestamp: Optional[float] = None) -> float:
        """
        Filter a noisy value.
        
        Args:
            x: The noisy input value
            timestamp: Optional timestamp (seconds). If not provided, uses time.time()
        
        Returns:
            Filtered (smoothed) value
        """
        if timestamp is None:
            timestamp = time.time()
        
        # Update frequency if we have a previous timestamp
        if self._last_time is not None and timestamp > self._last_time:
            self._freq = 1.0 / (timestamp - self._last_time)
        self._last_time = timestamp
        
        # Estimate derivative
        if self._x.has_last_raw_value():
            dx = (x - self._x.last_raw_value()) * self._freq
        else:
            dx = 0.0
        
        # Filter the derivative
        self._dx.set_alpha(self._alpha(self._d_cutoff))
        edx = self._dx.filter(dx)
        
        # Adaptive cutoff based on derivative magnitude
        cutoff = self._min_cutoff + self._beta * abs(edx)
        
        # Filter the signal
        self._x.set_alpha(self._alpha(cutoff))
        return self._x.filter(x)
    
    def reset(self):
        """Reset the filter state."""
        self._x = LowPassFilter()
        self._dx = LowPassFilter()
        self._last_time = None


class MultiDimensionalOneEuroFilter:
    """One Euro Filter for multi-dimensional data (e.g., 3D coordinates)."""
    
    def __init__(
        self,
        dimensions: int = 3,
        freq: float = 30.0,
        min_cutoff: float = 1.0,
        beta: float = 0.007,
        d_cutoff: float = 1.0,
    ):
        self._filters = [
            OneEuroFilter(freq, min_cutoff, beta, d_cutoff)
            for _ in range(dimensions)
        ]
    
    def filter(self, values: list, timestamp: Optional[float] = None) -> list:
        """Filter multi-dimensional values."""
        return [
            f.filter(v, timestamp)
            for f, v in zip(self._filters, values)
        ]
    
    def reset(self):
        """Reset all filters."""
        for f in self._filters:
            f.reset()

