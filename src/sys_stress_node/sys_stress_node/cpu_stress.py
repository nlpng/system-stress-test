import threading
import time
import math
import multiprocessing
import random
import argparse
import signal
import sys


class CPUStressTester:
    """CPU stress testing module with configurable intensity and duration"""
    
    def __init__(self, num_threads=None):
        self.num_threads = num_threads or multiprocessing.cpu_count()
        self.is_running = False
        self.threads = []
        self.stop_event = threading.Event()
        
    def _cpu_intensive_task(self, intensity=1.0):
        """Perform CPU-intensive calculations"""
        while not self.stop_event.is_set():
            # Perform mathematical operations to stress CPU
            for _ in range(int(10000 * intensity)):
                math.sqrt(math.factorial(10))
                math.sin(math.pi * random.random())
                math.log(abs(math.tan(random.random() * 10)) + 1)
            
            # Brief pause to allow for intensity control
            if intensity < 1.0:
                time.sleep(0.001 * (1.0 - intensity))
    
    def start_stress_test(self, intensity=0.8, duration=None):
        """
        Start CPU stress test
        
        Args:
            intensity (float): CPU load intensity (0.0 to 1.0)
            duration (float): Duration in seconds (None for indefinite)
        """
        if self.is_running:
            return False
            
        self.is_running = True
        self.stop_event.clear()
        
        # Create and start worker threads
        for i in range(self.num_threads):
            thread = threading.Thread(
                target=self._cpu_intensive_task,
                args=(intensity,),
                name=f"CPUStress-{i}"
            )
            thread.daemon = True
            self.threads.append(thread)
            thread.start()
        
        # Set timer to stop if duration specified
        if duration:
            timer = threading.Timer(duration, self.stop_stress_test)
            timer.start()
            
        return True
    
    def stop_stress_test(self):
        """Stop CPU stress test"""
        if not self.is_running:
            return False
            
        self.stop_event.set()
        self.is_running = False
        
        # Wait for all threads to complete
        for thread in self.threads:
            thread.join(timeout=1.0)
        
        self.threads.clear()
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
            'num_threads': self.num_threads,
            'active_threads': len([t for t in self.threads if t.is_alive()])
        }


def main():
    """Standalone CPU stress testing"""
    parser = argparse.ArgumentParser(description='CPU Stress Tester')
    parser.add_argument('--intensity', '-i', type=float, default=0.8,
                        help='CPU stress intensity (0.0 to 1.0, default: 0.8)')
    parser.add_argument('--duration', '-d', type=float, default=None,
                        help='Duration in seconds (default: indefinite)')
    parser.add_argument('--threads', '-t', type=int, default=None,
                        help='Number of threads (default: CPU count)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output with status updates')
    
    args = parser.parse_args()
    
    # Validate intensity
    if not 0.0 <= args.intensity <= 1.0:
        print("Error: Intensity must be between 0.0 and 1.0")
        sys.exit(1)
    
    # Create CPU stress tester
    tester = CPUStressTester(num_threads=args.threads)
    
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
    print(f"  Threads: {tester.num_threads}")
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
                print(f"\rRunning: {elapsed:.1f}s | Active threads: {status['active_threads']}/{status['num_threads']}", end='')
            time.sleep(1.0)
        
        print(f"\nCPU stress test completed after {time.time() - start_time:.1f} seconds")
        
    except KeyboardInterrupt:
        print("\nStopping CPU stress test...")
        tester.stop_stress_test()


if __name__ == '__main__':
    main()