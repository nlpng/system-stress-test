#!/usr/bin/env python3
"""
CPU Stress Testing Module

Generates configurable CPU load using multiprocessing for effective stress testing.
Algorithm: perform arithmetic operations for X% of time, sleep for (1-X)% of time.
"""

import time
import math
import random
import multiprocessing
import threading
import argparse
import signal
import sys
from typing import Optional


class CPUStressTester:
    """Generate CPU stress load across multiple cores with precise control."""
    
    def __init__(self, num_processes: Optional[int] = None):
        """
        Initialize CPU stress tester.
        
        Args:
            num_processes: Number of processes to use (default: all CPU cores)
        """
        self.cpu_cores = multiprocessing.cpu_count()
        self.num_processes = num_processes if num_processes is not None else self.cpu_cores
        self.processes = []
        self.is_running = False
        self.stop_event = multiprocessing.Event()
        self._shutdown_in_progress = False
        
    def start_stress_test(self, intensity: float = 0.8, duration: Optional[float] = None) -> bool:
        """
        Start CPU stress test.
        
        Args:
            intensity: CPU load intensity (0.0 to 1.0)
            duration: Duration in seconds (None for indefinite)
            
        Returns:
            True if started successfully, False if already running
        """
        if self.is_running:
            return False
            
        if not (0.0 <= intensity <= 1.0):
            raise ValueError("Intensity must be between 0.0 and 1.0")
            
        self.stop_event.clear()
        self.is_running = True
        self.processes = []
        
        # Start worker processes for each target core
        for i in range(self.num_processes):
            process = multiprocessing.Process(
                target=self._worker_process,
                args=(intensity, duration, self.stop_event),
                name=f"CPUStress-{i}"
            )
            self.processes.append(process)
            process.start()
            
        # Set timer to stop if duration specified
        if duration:
            timer = threading.Timer(duration, self.stop_stress_test)
            timer.start()
            
        return True
        
    def stop_stress_test(self) -> bool:
        """
        Stop CPU stress test.
        
        Returns:
            True if stopped successfully, False if not running
        """
        if not self.is_running or self._shutdown_in_progress:
            return False
            
        self._shutdown_in_progress = True
        self.stop_event.set()
        self.is_running = False
        
        # Wait for all processes to complete with more aggressive termination
        for process in self.processes:
            if process.is_alive():
                try:
                    process.join(timeout=1.0)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=0.5)
                        if process.is_alive():
                            process.kill()
                            process.join(timeout=0.5)
                except (OSError, AssertionError):
                    # Handle process cleanup errors gracefully
                    pass
                
        self.processes.clear()
        self._shutdown_in_progress = False
        return True
        
    @staticmethod
    def _worker_process(intensity: float, duration: Optional[float], stop_event: multiprocessing.Event) -> None:
        """
        Worker function that generates load on a single core.
        
        Args:
            intensity: CPU load intensity (0.0 to 1.0)
            duration: Duration in seconds (None for indefinite)
            stop_event: Event to signal early termination
        """
        # Ignore signals in worker processes to prevent signal propagation issues
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        
        try:
            # Calculate work and sleep times for each cycle
            cycle_time = 0.05  # 50ms cycles for more responsive control
            work_time = intensity * cycle_time
            sleep_time = cycle_time - work_time
            
            end_time = time.perf_counter() + duration if duration else float('inf')
            
            while time.perf_counter() < end_time and not stop_event.is_set():
                # Perform CPU-intensive work for calculated time
                work_start = time.perf_counter()
                
                # Do intensive computation without frequent stop checks to maintain CPU load
                while (time.perf_counter() - work_start) < work_time:
                    # Quick stop check every major iteration
                    if stop_event.is_set():
                        return
                    
                    # Intensive computation block - do more work per iteration
                    for _ in range(5000):  # Increased from 100 to 5000
                        x = random.random()
                        y = random.random()
                        # Multiple mathematical operations
                        result = math.sqrt(x) * math.pow(y, 2.5)
                        result += math.sin(x * math.pi) * math.cos(y * math.pi)
                        result += math.log(abs(result) + 1) * math.exp(x * 0.1)
                        result += math.atan(result) * math.asin(min(abs(y), 1.0))
                        # Prevent compiler optimization
                        if result > 1e10:
                            result = 0.0
                    
                # Sleep for the remaining cycle time
                if sleep_time > 0 and not stop_event.is_set():
                    time.sleep(sleep_time)
        except (KeyboardInterrupt, SystemExit):
            # Handle interruption gracefully
            return
    
    def get_status(self) -> dict:
        """Get current stress test status."""
        return {
            'running': self.is_running,
            'num_processes': self.num_processes,
            'active_processes': len([p for p in self.processes if p.is_alive()]),
            'cpu_cores': self.cpu_cores
        }
        
    def get_cpu_count(self) -> int:
        """Get the number of CPU cores available."""
        return self.cpu_cores


def main():
    """Standalone CPU stress testing with command-line interface."""
    parser = argparse.ArgumentParser(
        description='CPU Stress Tester - Generate configurable CPU load',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --intensity 0.5 --duration 60    # 50%% load for 60 seconds
  %(prog)s --intensity 1.0 --processes 4    # 100%% load on 4 cores
  %(prog)s --intensity 0.8 --verbose        # 80%% load with status updates
        """
    )
    
    parser.add_argument('--intensity', '-i', type=float, default=0.8,
                        help='CPU stress intensity (0.0 to 1.0, default: 0.8)')
    parser.add_argument('--duration', '-d', type=float, default=None,
                        help='Duration in seconds (default: indefinite)')
    parser.add_argument('--processes', '-p', type=int, default=None,
                        help='Number of processes (default: all CPU cores)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show verbose status updates')
    
    args = parser.parse_args()
    
    # Create and configure CPU stress tester
    try:
        tester = CPUStressTester(num_processes=args.processes)
        shutdown_requested = False
        
        # Setup graceful shutdown with protection against multiple calls
        def signal_handler(signum, frame):
            nonlocal shutdown_requested
            if shutdown_requested:
                # Force exit if already shutting down
                print("\nForced shutdown...")
                sys.exit(1)
            shutdown_requested = True
            print("\nStopping CPU stress test...")
            try:
                tester.stop_stress_test()
            except Exception as e:
                print(f"Error during shutdown: {e}")
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Display configuration
        print(f"CPU Stress Tester - Available cores: {tester.get_cpu_count()}")
        print(f"Starting stress test:")
        print(f"  Intensity: {args.intensity:.0%}")
        print(f"  Processes: {tester.num_processes}")
        print(f"  Duration: {args.duration if args.duration else 'Indefinite'}")
        print("Press Ctrl+C to stop")
        
        # Start stress test
        success = tester.start_stress_test(args.intensity, args.duration)
        
        if not success:
            print("Failed to start CPU stress test")
            sys.exit(1)
        
        # Monitor status
        start_time = time.time()
        try:
            while tester.is_running and not shutdown_requested:
                if args.verbose:
                    status = tester.get_status()
                    elapsed = time.time() - start_time
                    print(f"\rRunning: {elapsed:.1f}s | "
                          f"Active: {status['active_processes']}/{status['num_processes']} processes", 
                          end='', flush=True)
                time.sleep(1.0)
            
            if args.verbose and not shutdown_requested:
                print()  # New line after status updates
            if not shutdown_requested:
                print(f"CPU stress test completed after {time.time() - start_time:.1f} seconds")
            
        except KeyboardInterrupt:
            if not shutdown_requested:
                shutdown_requested = True
                print("\nStopping CPU stress test...")
                try:
                    tester.stop_stress_test()
                except Exception as e:
                    print(f"Error during shutdown: {e}")
            
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    # Required for multiprocessing on Windows
    multiprocessing.freeze_support()
    main()