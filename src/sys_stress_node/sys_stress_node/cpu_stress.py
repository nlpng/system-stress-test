import threading
import time
import math
import multiprocessing


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
                math.sin(math.pi * math.random())
                math.log(abs(math.tan(math.random() * 10)) + 1)
            
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