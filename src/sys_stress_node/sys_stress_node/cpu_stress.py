import threading
import time
import math
import multiprocessing
import random
import argparse
import signal
import sys
import os


def _cpu_worker_process(stop_flag, intensity):
    """Worker process for CPU stress testing"""
    while not stop_flag.value:
        # Time-based intensity control
        work_time = 0.1 * intensity  # Work for this fraction of time
        sleep_time = 0.1 * (1.0 - intensity)  # Sleep for the remainder
        
        # Work phase
        start_work = time.time()
        while (time.time() - start_work) < work_time and not stop_flag.value:
            # Heavy mathematical operations in tight loop
            for _ in range(100):
                if stop_flag.value:
                    break
                x = random.random() * 1000
                y = math.sin(x) + math.cos(x)
                z = math.sqrt(abs(y) + 1)
                w = math.pow(z, 1.5)
                result = math.log(w + 1)
        
        # Sleep phase for intensity control
        if sleep_time > 0 and not stop_flag.value:
            time.sleep(sleep_time)


class CPUStressTester:
    """CPU stress testing module with configurable intensity and duration"""
    
    def __init__(self, num_processes=None):
        self.num_processes = num_processes or multiprocessing.cpu_count()
        self.is_running = False
        self.processes = []
        self.stop_flags = []
    
    def start_stress_test(self, intensity=0.8, duration=None):
        """
        Start CPU stress test using multiprocessing
        
        Args:
            intensity (float): CPU load intensity (0.0 to 1.0)
            duration (float): Duration in seconds (None for indefinite)
        """
        if self.is_running:
            return False
            
        self.is_running = True
        self.processes.clear()
        self.stop_flags.clear()
        
        # Create and start worker processes
        for i in range(self.num_processes):
            stop_flag = multiprocessing.Value('i', 0)  # Shared integer flag
            self.stop_flags.append(stop_flag)
            
            process = multiprocessing.Process(
                target=_cpu_worker_process,
                args=(stop_flag, intensity),
                name=f"CPUStress-{i}"
            )
            process.start()
            self.processes.append(process)
        
        # Set timer to stop if duration specified
        if duration:
            timer = threading.Timer(duration, self.stop_stress_test)
            timer.start()
            
        return True
    
    def stop_stress_test(self):
        """Stop CPU stress test"""
        if not self.is_running:
            return False
            
        self.is_running = False
        
        # Signal all processes to stop
        for stop_flag in self.stop_flags:
            stop_flag.value = 1
        
        # Wait for all processes to complete
        for process in self.processes:
            process.join(timeout=2.0)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
        
        self.processes.clear()
        self.stop_flags.clear()
        return True
    
    def adjust_intensity(self, intensity):
        """Adjust stress test intensity (requires restart)"""
        if self.is_running:
            self.stop_stress_test()
            time.sleep(0.1)
            self.start_stress_test(intensity)
    
    def get_status(self):
        """Get current stress test status"""
        return {
            'running': self.is_running,
            'num_processes': self.num_processes,
            'active_processes': len([p for p in self.processes if p.is_alive()])
        }


def main():
    """Standalone CPU stress testing"""
    parser = argparse.ArgumentParser(description='CPU Stress Tester')
    parser.add_argument('--intensity', '-i', type=float, default=0.8,
                        help='CPU stress intensity (0.0 to 1.0, default: 0.8)')
    parser.add_argument('--duration', '-d', type=float, default=None,
                        help='Duration in seconds (default: indefinite)')
    parser.add_argument('--processes', '-p', type=int, default=None,
                        help='Number of processes (default: CPU count)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output with status updates')
    
    args = parser.parse_args()
    
    # Validate intensity
    if not 0.0 <= args.intensity <= 1.0:
        print("Error: Intensity must be between 0.0 and 1.0")
        sys.exit(1)
    
    # Create CPU stress tester
    tester = CPUStressTester(num_processes=args.processes)
    
    # Setup signal handler for graceful shutdown
    def signal_handler(signum, frame):
        print("\nReceived shutdown signal, stopping CPU stress test...")
        tester.stop_stress_test()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start stress test
    print(f"Starting CPU stress test:")
    print(f"  Intensity: {args.intensity:.2f}")
    print(f"  Processes: {tester.num_processes}")
    print(f"  Duration: {args.duration if args.duration else 'Indefinite'}")
    print("Press Ctrl+C to stop")
    
    success = tester.start_stress_test(args.intensity, args.duration)
    
    if not success:
        print("Failed to start CPU stress test")
        sys.exit(1)
    
    # Monitor and display status
    try:
        start_time = time.time()
        while tester.is_running:
            if args.verbose:
                status = tester.get_status()
                elapsed = time.time() - start_time
                print(f"\rRunning: {elapsed:.1f}s | Active processes: {status['active_processes']}/{status['num_processes']}", end='')
            time.sleep(1.0)
        
        print(f"\nCPU stress test completed after {time.time() - start_time:.1f} seconds")
        
    except KeyboardInterrupt:
        print("\nStopping CPU stress test...")
        tester.stop_stress_test()


if __name__ == '__main__':
    # Required for multiprocessing on Windows
    multiprocessing.freeze_support()
    main()