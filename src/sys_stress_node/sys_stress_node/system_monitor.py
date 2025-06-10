import psutil
import threading
import time
from collections import deque


class SystemMonitor:
    """System resource monitoring with safety limits and alerts"""
    
    def __init__(self, history_size=60):
        self.history_size = history_size
        self.cpu_history = deque(maxlen=history_size)
        self.memory_history = deque(maxlen=history_size)
        self.is_monitoring = False
        self.monitor_thread = None
        self.stop_event = threading.Event()
        
        # Safety thresholds
        self.cpu_warning_threshold = 90.0
        self.cpu_critical_threshold = 95.0
        self.memory_warning_threshold = 85.0
        self.memory_critical_threshold = 95.0
        
        # Alert callbacks
        self.alert_callbacks = []
        
    def add_alert_callback(self, callback):
        """Add callback function for system alerts"""
        self.alert_callbacks.append(callback)
        
    def _monitor_loop(self):
        """Main monitoring loop"""
        while not self.stop_event.is_set():
            try:
                # Get current system metrics
                cpu_percent = psutil.cpu_percent(interval=1.0)
                memory = psutil.virtual_memory()
                memory_percent = memory.percent
                
                # Store in history
                timestamp = time.time()
                self.cpu_history.append((timestamp, cpu_percent))
                self.memory_history.append((timestamp, memory_percent))
                
                # Check for critical conditions
                self._check_alerts(cpu_percent, memory_percent)
                
            except Exception as e:
                print(f"Monitoring error: {e}")
                time.sleep(1.0)
    
    def _check_alerts(self, cpu_percent, memory_percent):
        """Check for alert conditions and trigger callbacks"""
        alerts = []
        
        # CPU alerts
        if cpu_percent >= self.cpu_critical_threshold:
            alerts.append({
                'type': 'cpu_critical',
                'value': cpu_percent,
                'threshold': self.cpu_critical_threshold,
                'message': f'Critical CPU usage: {cpu_percent:.1f}%'
            })
        elif cpu_percent >= self.cpu_warning_threshold:
            alerts.append({
                'type': 'cpu_warning',
                'value': cpu_percent,
                'threshold': self.cpu_warning_threshold,
                'message': f'High CPU usage: {cpu_percent:.1f}%'
            })
        
        # Memory alerts
        if memory_percent >= self.memory_critical_threshold:
            alerts.append({
                'type': 'memory_critical',
                'value': memory_percent,
                'threshold': self.memory_critical_threshold,
                'message': f'Critical memory usage: {memory_percent:.1f}%'
            })
        elif memory_percent >= self.memory_warning_threshold:
            alerts.append({
                'type': 'memory_warning',
                'value': memory_percent,
                'threshold': self.memory_warning_threshold,
                'message': f'High memory usage: {memory_percent:.1f}%'
            })
        
        # Trigger alert callbacks
        for alert in alerts:
            for callback in self.alert_callbacks:
                try:
                    callback(alert)
                except Exception as e:
                    print(f"Alert callback error: {e}")
    
    def start_monitoring(self):
        """Start system monitoring"""
        if self.is_monitoring:
            return False
            
        self.is_monitoring = True
        self.stop_event.clear()
        
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="SystemMonitor"
        )
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        return True
    
    def stop_monitoring(self):
        """Stop system monitoring"""
        if not self.is_monitoring:
            return False
            
        self.stop_event.set()
        self.is_monitoring = False
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
            
        return True
    
    def get_current_stats(self):
        """Get current system statistics"""
        cpu_percent = psutil.cpu_percent()
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        return {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'memory_available_mb': memory.available / (1024 * 1024),
            'memory_used_mb': memory.used / (1024 * 1024),
            'memory_total_mb': memory.total / (1024 * 1024),
            'disk_percent': disk.percent,
            'disk_free_gb': disk.free / (1024 * 1024 * 1024),
            'load_average': psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None
        }
    
    def get_history_stats(self, duration_seconds=60):
        """Get historical statistics for specified duration"""
        current_time = time.time()
        cutoff_time = current_time - duration_seconds
        
        # Filter history by time
        cpu_recent = [(t, v) for t, v in self.cpu_history if t >= cutoff_time]
        memory_recent = [(t, v) for t, v in self.memory_history if t >= cutoff_time]
        
        if not cpu_recent or not memory_recent:
            return None
            
        # Calculate statistics
        cpu_values = [v for _, v in cpu_recent]
        memory_values = [v for _, v in memory_recent]
        
        return {
            'cpu_avg': sum(cpu_values) / len(cpu_values),
            'cpu_max': max(cpu_values),
            'cpu_min': min(cpu_values),
            'memory_avg': sum(memory_values) / len(memory_values),
            'memory_max': max(memory_values),
            'memory_min': min(memory_values),
            'sample_count': len(cpu_values),
            'duration_seconds': duration_seconds
        }
    
    def is_system_safe(self):
        """Check if system is in safe operating condition"""
        stats = self.get_current_stats()
        return (stats['cpu_percent'] < self.cpu_critical_threshold and 
                stats['memory_percent'] < self.memory_critical_threshold)
    
    def get_status(self):
        """Get monitoring status"""
        return {
            'monitoring': self.is_monitoring,
            'history_size': len(self.cpu_history),
            'thresholds': {
                'cpu_warning': self.cpu_warning_threshold,
                'cpu_critical': self.cpu_critical_threshold,
                'memory_warning': self.memory_warning_threshold,
                'memory_critical': self.memory_critical_threshold
            }
        }