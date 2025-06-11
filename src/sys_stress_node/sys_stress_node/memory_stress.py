import threading
import time
import gc
import psutil
import argparse
import signal
import sys


class MemoryStressTester:
    """Memory stress testing module with configurable allocation patterns"""
    
    def __init__(self):
        self.is_running = False
        self.allocated_chunks = []
        self.stop_event = threading.Event()
        self.worker_thread = None
        self.total_allocated_mb = 0
        
    def _memory_allocation_task(self, target_mb, chunk_size_mb=10):
        """Perform memory allocation and deallocation patterns"""
        current_allocated = 0
        
        while not self.stop_event.is_set() and current_allocated < target_mb:
            try:
                # Allocate memory chunk (filled with data to ensure actual allocation)
                chunk_size_bytes = chunk_size_mb * 1024 * 1024
                chunk = bytearray(chunk_size_bytes)
                
                # Fill with pattern to prevent optimization
                for i in range(0, len(chunk), 1024):
                    chunk[i:i+8] = b'STRESS!!'
                
                self.allocated_chunks.append(chunk)
                current_allocated += chunk_size_mb
                self.total_allocated_mb = current_allocated
                
                # Brief pause between allocations
                time.sleep(0.1)
                
            except MemoryError:
                break
        
        # Hold memory for specified duration or until stopped
        while not self.stop_event.is_set():
            time.sleep(0.5)
            
            # Periodically access memory to prevent swapping
            if self.allocated_chunks:
                chunk = self.allocated_chunks[0]
                _ = chunk[0:100]  # Access small portion
    
    def start_stress_test(self, target_mb=512, duration=None):
        """
        Start memory stress test
        
        Args:
            target_mb (int): Target memory allocation in MB
            duration (float): Duration in seconds (None for indefinite)
        """
        if self.is_running:
            return False
        
        # Safety check - don't allocate more than 80% of available memory
        available_mb = psutil.virtual_memory().available / (1024 * 1024)
        max_safe_mb = int(available_mb * 0.8)
        
        if target_mb > max_safe_mb:
            target_mb = max_safe_mb
            
        self.is_running = True
        self.stop_event.clear()
        self.allocated_chunks.clear()
        self.total_allocated_mb = 0
        
        # Start memory allocation thread
        self.worker_thread = threading.Thread(
            target=self._memory_allocation_task,
            args=(target_mb,),
            name="MemoryStress"
        )
        self.worker_thread.daemon = True
        self.worker_thread.start()
        
        # Set timer to stop if duration specified
        if duration:
            timer = threading.Timer(duration, self.stop_stress_test)
            timer.start()
            
        return True
    
    def stop_stress_test(self):
        """Stop memory stress test and free allocated memory"""
        if not self.is_running:
            return False
            
        self.stop_event.set()
        self.is_running = False
        
        # Wait for worker thread to complete
        if self.worker_thread:
            self.worker_thread.join(timeout=2.0)
        
        # Free allocated memory
        self.allocated_chunks.clear()
        self.total_allocated_mb = 0
        
        # Force garbage collection
        gc.collect()
        
        return True
    
    def get_memory_usage(self):
        """Get current memory usage statistics"""
        process = psutil.Process()
        system_memory = psutil.virtual_memory()
        
        return {
            'process_memory_mb': process.memory_info().rss / (1024 * 1024),
            'allocated_chunks': len(self.allocated_chunks),
            'total_allocated_mb': self.total_allocated_mb,
            'system_memory_percent': system_memory.percent,
            'system_available_mb': system_memory.available / (1024 * 1024)
        }
    
    def get_status(self):
        """Get current stress test status"""
        return {
            'running': self.is_running,
            'allocated_chunks': len(self.allocated_chunks),
            'total_allocated_mb': self.total_allocated_mb,
            'worker_alive': self.worker_thread.is_alive() if self.worker_thread else False
        }


def main():
    """Standalone memory stress testing"""
    parser = argparse.ArgumentParser(description='Memory Stress Tester')
    parser.add_argument('--target', '-t', type=int, default=512,
                        help='Target memory allocation in MB (default: 512)')
    parser.add_argument('--duration', '-d', type=float, default=None,
                        help='Duration in seconds (default: indefinite)')
    parser.add_argument('--chunk-size', '-c', type=int, default=10,
                        help='Allocation chunk size in MB (default: 10)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output with status updates')
    parser.add_argument('--show-system-info', '-s', action='store_true',
                        help='Show system memory information')
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.target <= 0:
        print("Error: Target memory must be positive")
        sys.exit(1)
        
    if args.chunk_size <= 0:
        print("Error: Chunk size must be positive")
        sys.exit(1)
    
    # Show system info if requested
    if args.show_system_info:
        memory = psutil.virtual_memory()
        print(f"System Memory Information:")
        print(f"  Total: {memory.total / (1024**3):.1f} GB")
        print(f"  Available: {memory.available / (1024**3):.1f} GB")
        print(f"  Used: {memory.used / (1024**3):.1f} GB ({memory.percent:.1f}%)")
        print(f"  Free: {memory.free / (1024**3):.1f} GB")
        print()
    
    # Create memory stress tester
    tester = MemoryStressTester()
    
    # Setup signal handler for graceful shutdown
    def signal_handler(signum, frame):
        print("\nReceived shutdown signal, stopping memory stress test...")
        tester.stop_stress_test()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Check available memory and adjust target if needed
    available_mb = psutil.virtual_memory().available / (1024 * 1024)
    max_safe_mb = int(available_mb * 0.8)
    
    if args.target > max_safe_mb:
        print(f"Warning: Target {args.target}MB exceeds safe limit of {max_safe_mb}MB")
        print(f"Adjusting target to {max_safe_mb}MB for safety")
        args.target = max_safe_mb
    
    # Start stress test
    print(f"Starting memory stress test:")
    print(f"  Target: {args.target} MB")
    print(f"  Chunk size: {args.chunk_size} MB")
    print(f"  Duration: {args.duration if args.duration else 'Indefinite'}")
    print("Press Ctrl+C to stop")
    
    success = tester.start_stress_test(args.target, args.duration)
    
    if not success:
        print("Failed to start memory stress test")
        sys.exit(1)
    
    # Monitor and display status
    try:
        start_time = time.time()
        while tester.is_running:
            if args.verbose:
                status = tester.get_status()
                memory_usage = tester.get_memory_usage()
                elapsed = time.time() - start_time
                
                print(f"\rRunning: {elapsed:.1f}s | "
                      f"Allocated: {status['total_allocated_mb']:.0f}MB | "
                      f"Chunks: {status['allocated_chunks']} | "
                      f"System: {memory_usage['system_memory_percent']:.1f}%", end='')
            time.sleep(1.0)
        
        final_status = tester.get_status()
        print(f"\nMemory stress test completed after {time.time() - start_time:.1f} seconds")
        print(f"Peak allocation: {final_status['total_allocated_mb']:.0f} MB")
        
    except KeyboardInterrupt:
        print("\nStopping memory stress test...")
        tester.stop_stress_test()
        print("Memory freed and test stopped")


if __name__ == '__main__':
    main()