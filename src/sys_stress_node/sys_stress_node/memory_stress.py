import threading
import time
import gc
import psutil


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