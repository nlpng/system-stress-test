#!/usr/bin/env python3
"""
Baseline Performance Collector

Measures and stores baseline system performance without any artificial stress.
Provides reference metrics for comparing stressed vs unstressed system performance.
"""

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_msgs.msg import String, Bool
from std_srvs.srv import Trigger, SetBool
import json
import time
import threading
import statistics
import psutil
import os
from collections import deque
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime
import numpy as np


@dataclass
class BaselineSystemMetrics:
    """System resource metrics during baseline measurement."""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_available_gb: float
    network_bytes_sent_rate: float  # bytes per second
    network_bytes_recv_rate: float  # bytes per second
    disk_read_rate: float  # bytes per second
    disk_write_rate: float  # bytes per second
    load_average_1min: float
    process_count: int
    context_switches_rate: float  # switches per second


@dataclass
class BaselineMessageMetrics:
    """Message performance metrics during baseline measurement."""
    timestamp: float
    message_type: str
    latency_ms: float
    throughput_hz: float
    payload_size: int
    serialization_time_us: float
    deserialization_time_us: float


@dataclass
class BaselineSummary:
    """Complete baseline performance summary."""
    measurement_start: float
    measurement_duration: float
    system_idle_confirmed: bool
    
    # System resource baseline
    cpu_baseline: Dict[str, float]  # min, max, mean, std
    memory_baseline: Dict[str, float]
    network_baseline: Dict[str, float]
    disk_baseline: Dict[str, float]
    load_baseline: Dict[str, float]
    
    # Message performance baseline
    message_baselines: Dict[str, Dict[str, float]]  # per message type
    
    # Overall system health indicators
    system_stability_score: float  # 0-1, higher is more stable
    measurement_quality: str  # 'excellent', 'good', 'fair', 'poor'
    warnings: List[str]


class BaselineCollector(Node):
    """Collects baseline performance measurements without artificial stress."""
    
    def __init__(self):
        super().__init__('baseline_collector')
        
        # Declare parameters
        self.declare_parameter('measurement_duration', 300.0)  # 5 minutes default
        self.declare_parameter('sample_interval', 1.0)  # 1 second sampling
        self.declare_parameter('idle_detection_threshold', 30.0)  # 30% CPU threshold
        self.declare_parameter('idle_detection_duration', 60.0)  # 60 seconds idle required
        self.declare_parameter('baseline_file', 'baseline_performance.json')
        self.declare_parameter('auto_validate_idle', True)
        self.declare_parameter('message_test_rate', 1.0)  # Low rate for baseline message testing
        self.declare_parameter('message_test_payload', 1024)  # Small payload for baseline
        self.declare_parameter('stability_threshold', 0.8)  # Stability score threshold
        self.declare_parameter('warmup_duration', 30.0)  # System warmup before measurement
        
        # Initialize state
        self.is_measuring = False
        self.measurement_start_time = None
        self.system_metrics_history = deque()
        self.message_metrics_history = deque()
        self.idle_validated = False
        self.current_baseline = None
        
        # System monitoring setup
        self.previous_network_stats = None
        self.previous_disk_stats = None
        self.previous_cpu_times = None
        self.previous_sample_time = None
        
        # Thread safety
        self.collector_lock = threading.Lock()
        
        # Setup ROS 2 interfaces
        self._setup_services()
        self._setup_publishers()
        self._setup_subscribers()
        
        # Initialize system monitoring
        self._initialize_system_monitoring()
        
        # Load existing baseline if available
        self._load_existing_baseline()
        
        self.get_logger().info("BaselineCollector initialized")
        self.get_logger().info(f"  Measurement duration: {self.get_parameter('measurement_duration').value}s")
        self.get_logger().info(f"  Idle detection: {self.get_parameter('auto_validate_idle').value}")
        self.get_logger().info(f"  Baseline file: {self.get_parameter('baseline_file').value}")
        
    def _setup_services(self):
        """Setup ROS 2 services for baseline control."""
        self.start_baseline_srv = self.create_service(
            Trigger, 'start_baseline_measurement', self._start_baseline_service
        )
        self.stop_baseline_srv = self.create_service(
            Trigger, 'stop_baseline_measurement', self._stop_baseline_service
        )
        self.get_baseline_srv = self.create_service(
            Trigger, 'get_baseline_summary', self._get_baseline_service
        )
        self.validate_idle_srv = self.create_service(
            Trigger, 'validate_system_idle', self._validate_idle_service
        )
        self.save_baseline_srv = self.create_service(
            Trigger, 'save_baseline', self._save_baseline_service
        )
        
    def _setup_publishers(self):
        """Setup ROS 2 publishers for baseline status."""
        self.baseline_status_pub = self.create_publisher(
            String, 'baseline_status', 10
        )
        self.baseline_metrics_pub = self.create_publisher(
            String, 'baseline_metrics', 10
        )
        self.system_idle_pub = self.create_publisher(
            Bool, 'system_idle_status', 10
        )
        
    def _setup_subscribers(self):
        """Setup ROS 2 subscribers for monitoring."""
        # Subscribe to any existing stress test metrics to detect interference
        self.stress_metrics_subscriber = self.create_subscription(
            String, 'aggregated_metrics', self._stress_metrics_callback, 10
        )
        
    def _initialize_system_monitoring(self):
        """Initialize system monitoring baselines."""
        try:
            # Initialize psutil
            self.process = psutil.Process()
            
            # Get initial readings for rate calculations
            self.previous_network_stats = psutil.net_io_counters()
            self.previous_disk_stats = psutil.disk_io_counters()
            self.previous_cpu_times = psutil.cpu_times()
            self.previous_sample_time = time.time()
            
            # System info
            self.system_info = {
                'cpu_count': psutil.cpu_count(),
                'memory_total_gb': psutil.virtual_memory().total / (1024**3),
                'boot_time': psutil.boot_time(),
                'platform': psutil.os.name
            }
            
            self.get_logger().info(f"System info: {self.system_info['cpu_count']} CPUs, "
                                 f"{self.system_info['memory_total_gb']:.1f} GB RAM")
            
        except Exception as e:
            self.get_logger().error(f"Failed to initialize system monitoring: {e}")
            
    def _start_baseline_service(self, request, response):
        """Service to start baseline measurement."""
        try:
            success, message = self.start_baseline_measurement()
            response.success = success
            response.message = message
            
        except Exception as e:
            response.success = False
            response.message = f"Error starting baseline measurement: {e}"
            self.get_logger().error(f"Service error: {e}")
            
        return response
        
    def _stop_baseline_service(self, request, response):
        """Service to stop baseline measurement."""
        try:
            success, message = self.stop_baseline_measurement()
            response.success = success
            response.message = message
            
        except Exception as e:
            response.success = False
            response.message = f"Error stopping baseline measurement: {e}"
            
        return response
        
    def _get_baseline_service(self, request, response):
        """Service to get baseline summary."""
        try:
            if self.current_baseline:
                baseline_dict = asdict(self.current_baseline)
                response.success = True
                response.message = json.dumps(baseline_dict, indent=2, default=str)
            else:
                response.success = False
                response.message = "No baseline measurement available"
                
        except Exception as e:
            response.success = False
            response.message = f"Error getting baseline: {e}"
            
        return response
        
    def _validate_idle_service(self, request, response):
        """Service to validate system is idle."""
        try:
            is_idle, message = self.validate_system_idle()
            response.success = is_idle
            response.message = message
            
        except Exception as e:
            response.success = False
            response.message = f"Error validating idle state: {e}"
            
        return response
        
    def _save_baseline_service(self, request, response):
        """Service to save current baseline."""
        try:
            success = self.save_baseline_to_file()
            response.success = success
            response.message = "Baseline saved successfully" if success else "Failed to save baseline"
            
        except Exception as e:
            response.success = False
            response.message = f"Error saving baseline: {e}"
            
        return response
        
    def start_baseline_measurement(self) -> Tuple[bool, str]:
        """Start baseline performance measurement."""
        with self.collector_lock:
            if self.is_measuring:
                return False, "Baseline measurement already in progress"
                
            # Validate system is idle if configured
            if self.get_parameter('auto_validate_idle').value:
                is_idle, idle_message = self.validate_system_idle()
                if not is_idle:
                    return False, f"System not idle: {idle_message}"
                    
            # Clear previous data
            self.system_metrics_history.clear()
            self.message_metrics_history.clear()
            
            # Start measurement
            self.is_measuring = True
            self.measurement_start_time = time.time()
            
            # Start measurement timer
            measurement_duration = self.get_parameter('measurement_duration').value
            sample_interval = self.get_parameter('sample_interval').value
            
            # Setup measurement timer
            self.measurement_timer = self.create_timer(sample_interval, self._collect_baseline_sample)
            
            # Setup completion timer
            self.completion_timer = self.create_timer(measurement_duration, self._complete_baseline_measurement)
            
            self.get_logger().info(f"Starting baseline measurement for {measurement_duration}s")
            self._publish_status("started")
            
            return True, f"Baseline measurement started for {measurement_duration} seconds"
            
    def stop_baseline_measurement(self) -> Tuple[bool, str]:
        """Stop baseline performance measurement."""
        with self.collector_lock:
            if not self.is_measuring:
                return False, "No baseline measurement in progress"
                
            self._complete_baseline_measurement()
            return True, "Baseline measurement stopped"
            
    def validate_system_idle(self) -> Tuple[bool, str]:
        """Validate that the system is idle enough for baseline measurement."""
        try:
            idle_threshold = self.get_parameter('idle_detection_threshold').value
            idle_duration = self.get_parameter('idle_detection_duration').value
            sample_interval = 2.0  # Sample every 2 seconds during validation
            
            self.get_logger().info(f"Validating system idle state for {idle_duration}s...")
            
            # Collect samples over the idle detection duration
            samples = []
            start_time = time.time()
            
            while (time.time() - start_time) < idle_duration:
                # Get current system metrics
                cpu_percent = psutil.cpu_percent(interval=1.0)
                memory = psutil.virtual_memory()
                
                # Check for high resource usage
                if cpu_percent > idle_threshold:
                    return False, f"CPU usage too high: {cpu_percent:.1f}% > {idle_threshold}%"
                    
                if memory.percent > 85.0:  # High memory usage threshold
                    return False, f"Memory usage too high: {memory.percent:.1f}% > 85%"
                    
                samples.append({
                    'cpu': cpu_percent,
                    'memory': memory.percent,
                    'timestamp': time.time()
                })
                
                time.sleep(sample_interval)
                
            # Analyze stability of measurements
            cpu_values = [s['cpu'] for s in samples]
            cpu_std = statistics.stdev(cpu_values) if len(cpu_values) > 1 else 0
            cpu_mean = statistics.mean(cpu_values)
            
            # Check for stability (low variance indicates idle system)
            if cpu_std > 10.0:  # High variance threshold
                return False, f"System too unstable: CPU std={cpu_std:.1f}% (mean={cpu_mean:.1f}%)"
                
            self.idle_validated = True
            self.get_logger().info(f"System validated as idle: CPU avg={cpu_mean:.1f}%, std={cpu_std:.1f}%")
            
            # Publish idle status
            idle_msg = Bool()
            idle_msg.data = True
            self.system_idle_pub.publish(idle_msg)
            
            return True, f"System idle validated: CPU avg={cpu_mean:.1f}%, std={cpu_std:.1f}%"
            
        except Exception as e:
            self.get_logger().error(f"Error validating idle state: {e}")
            return False, f"Validation error: {e}"
            
    def _collect_baseline_sample(self):
        """Collect a single baseline sample."""
        if not self.is_measuring:
            return
            
        try:
            current_time = time.time()
            
            # Collect system metrics
            system_metrics = self._collect_system_metrics(current_time)
            if system_metrics:
                self.system_metrics_history.append(system_metrics)
                
            # Collect message metrics (minimal rate during baseline)
            message_metrics = self._collect_message_metrics(current_time)
            if message_metrics:
                self.message_metrics_history.append(message_metrics)
                
            # Publish real-time metrics
            self._publish_current_metrics(system_metrics, message_metrics)
            
        except Exception as e:
            self.get_logger().error(f"Error collecting baseline sample: {e}")
            
    def _collect_system_metrics(self, timestamp: float) -> Optional[BaselineSystemMetrics]:
        """Collect system resource metrics."""
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=None)
            
            # Memory metrics
            memory = psutil.virtual_memory()
            
            # Network metrics (calculate rates)
            current_network = psutil.net_io_counters()
            network_sent_rate = 0.0
            network_recv_rate = 0.0
            
            if self.previous_network_stats and self.previous_sample_time:
                time_delta = timestamp - self.previous_sample_time
                if time_delta > 0:
                    network_sent_rate = (current_network.bytes_sent - self.previous_network_stats.bytes_sent) / time_delta
                    network_recv_rate = (current_network.bytes_recv - self.previous_network_stats.bytes_recv) / time_delta
                    
            # Disk metrics (calculate rates)
            current_disk = psutil.disk_io_counters()
            disk_read_rate = 0.0
            disk_write_rate = 0.0
            
            if current_disk and self.previous_disk_stats and self.previous_sample_time:
                time_delta = timestamp - self.previous_sample_time
                if time_delta > 0:
                    disk_read_rate = (current_disk.read_bytes - self.previous_disk_stats.read_bytes) / time_delta
                    disk_write_rate = (current_disk.write_bytes - self.previous_disk_stats.write_bytes) / time_delta
                    
            # System load and process metrics
            load_avg = psutil.getloadavg()[0] if hasattr(psutil, 'getloadavg') else 0.0
            process_count = len(psutil.pids())
            
            # Context switches (if available)
            context_switches_rate = 0.0
            try:
                cpu_stats = psutil.cpu_stats()
                if hasattr(cpu_stats, 'ctx_switches') and self.previous_sample_time:
                    # This is a cumulative counter, would need previous value for rate
                    context_switches_rate = float(cpu_stats.ctx_switches)
            except:
                pass
                
            # Update previous values for next calculation
            self.previous_network_stats = current_network
            self.previous_disk_stats = current_disk
            self.previous_sample_time = timestamp
            
            return BaselineSystemMetrics(
                timestamp=timestamp,
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_available_gb=memory.available / (1024**3),
                network_bytes_sent_rate=network_sent_rate,
                network_bytes_recv_rate=network_recv_rate,
                disk_read_rate=disk_read_rate,
                disk_write_rate=disk_write_rate,
                load_average_1min=load_avg,
                process_count=process_count,
                context_switches_rate=context_switches_rate
            )
            
        except Exception as e:
            self.get_logger().debug(f"Error collecting system metrics: {e}")
            return None
            
    def _collect_message_metrics(self, timestamp: float) -> Optional[BaselineMessageMetrics]:
        """Collect minimal message performance metrics."""
        try:
            # Test basic string message performance at low rate
            test_rate = self.get_parameter('message_test_rate').value
            
            # Only test once per second during baseline (don't flood system)
            if hasattr(self, '_last_message_test') and (timestamp - self._last_message_test) < (1.0 / test_rate):
                return None
                
            self._last_message_test = timestamp
            
            # Simple latency test: measure time to create and serialize message
            start_time = time.perf_counter()
            
            # Create test message
            from std_msgs.msg import String
            test_msg = String()
            test_msg.data = f"baseline_test_{timestamp}_{self.get_parameter('message_test_payload').value}"
            
            serialization_time = time.perf_counter() - start_time
            
            # Measure deserialization (simplified)
            deserial_start = time.perf_counter()
            _ = len(test_msg.data)  # Simple access operation
            deserialization_time = time.perf_counter() - deserial_start
            
            # Calculate simple latency (in-process, minimal overhead)
            latency_ms = (serialization_time + deserialization_time) * 1000.0
            
            return BaselineMessageMetrics(
                timestamp=timestamp,
                message_type='string',
                latency_ms=latency_ms,
                throughput_hz=test_rate,
                payload_size=len(test_msg.data),
                serialization_time_us=serialization_time * 1_000_000,
                deserialization_time_us=deserialization_time * 1_000_000
            )
            
        except Exception as e:
            self.get_logger().debug(f"Error collecting message metrics: {e}")
            return None
            
    def _complete_baseline_measurement(self):
        """Complete baseline measurement and generate summary."""
        with self.collector_lock:
            if not self.is_measuring:
                return
                
            # Stop timers
            if hasattr(self, 'measurement_timer'):
                self.measurement_timer.cancel()
            if hasattr(self, 'completion_timer'):
                self.completion_timer.cancel()
                
            self.is_measuring = False
            measurement_end_time = time.time()
            measurement_duration = measurement_end_time - self.measurement_start_time
            
            self.get_logger().info(f"Completing baseline measurement after {measurement_duration:.1f}s")
            
            # Generate baseline summary
            self.current_baseline = self._generate_baseline_summary(measurement_duration)
            
            # Automatically save baseline
            self.save_baseline_to_file()
            
            # Publish completion status
            self._publish_status("completed")
            self._publish_baseline_summary()
            
            self.get_logger().info(f"Baseline measurement completed:")
            self.get_logger().info(f"  Quality: {self.current_baseline.measurement_quality}")
            self.get_logger().info(f"  Stability score: {self.current_baseline.system_stability_score:.3f}")
            self.get_logger().info(f"  CPU baseline: {self.current_baseline.cpu_baseline['mean']:.1f}% ± {self.current_baseline.cpu_baseline['std']:.1f}%")
            self.get_logger().info(f"  Memory baseline: {self.current_baseline.memory_baseline['mean']:.1f}%")
            
    def _generate_baseline_summary(self, duration: float) -> BaselineSummary:
        """Generate comprehensive baseline summary from collected data."""
        current_time = time.time()
        
        # Process system metrics
        if self.system_metrics_history:
            system_data = list(self.system_metrics_history)
            
            # CPU statistics
            cpu_values = [m.cpu_percent for m in system_data]
            cpu_baseline = self._calculate_statistics(cpu_values)
            
            # Memory statistics
            memory_values = [m.memory_percent for m in system_data]
            memory_baseline = self._calculate_statistics(memory_values)
            
            # Network statistics
            network_sent_values = [m.network_bytes_sent_rate for m in system_data]
            network_recv_values = [m.network_bytes_recv_rate for m in system_data]
            network_baseline = {
                'sent_rate': self._calculate_statistics(network_sent_values),
                'recv_rate': self._calculate_statistics(network_recv_values)
            }
            
            # Disk statistics
            disk_read_values = [m.disk_read_rate for m in system_data]
            disk_write_values = [m.disk_write_rate for m in system_data]
            disk_baseline = {
                'read_rate': self._calculate_statistics(disk_read_values),
                'write_rate': self._calculate_statistics(disk_write_values)
            }
            
            # Load average statistics
            load_values = [m.load_average_1min for m in system_data]
            load_baseline = self._calculate_statistics(load_values)
            
        else:
            # No data collected
            cpu_baseline = memory_baseline = network_baseline = disk_baseline = load_baseline = {}
            
        # Process message metrics
        message_baselines = {}
        if self.message_metrics_history:
            message_data = list(self.message_metrics_history)
            
            # Group by message type
            by_type = {}
            for msg in message_data:
                if msg.message_type not in by_type:
                    by_type[msg.message_type] = []
                by_type[msg.message_type].append(msg)
                
            for msg_type, msgs in by_type.items():
                latencies = [m.latency_ms for m in msgs]
                throughputs = [m.throughput_hz for m in msgs]
                serial_times = [m.serialization_time_us for m in msgs]
                
                message_baselines[msg_type] = {
                    'latency': self._calculate_statistics(latencies),
                    'throughput': self._calculate_statistics(throughputs),
                    'serialization': self._calculate_statistics(serial_times)
                }
                
        # Calculate system stability score
        stability_score = self._calculate_stability_score(cpu_baseline, memory_baseline)
        
        # Determine measurement quality
        quality = self._determine_measurement_quality(stability_score, duration, len(self.system_metrics_history))
        
        # Generate warnings
        warnings = self._generate_warnings(cpu_baseline, memory_baseline, stability_score)
        
        return BaselineSummary(
            measurement_start=self.measurement_start_time,
            measurement_duration=duration,
            system_idle_confirmed=self.idle_validated,
            cpu_baseline=cpu_baseline,
            memory_baseline=memory_baseline,
            network_baseline=network_baseline,
            disk_baseline=disk_baseline,
            load_baseline=load_baseline,
            message_baselines=message_baselines,
            system_stability_score=stability_score,
            measurement_quality=quality,
            warnings=warnings
        )
        
    def _calculate_statistics(self, values: List[float]) -> Dict[str, float]:
        """Calculate statistical summary for a list of values."""
        if not values:
            return {'min': 0.0, 'max': 0.0, 'mean': 0.0, 'std': 0.0, 'median': 0.0}
            
        return {
            'min': float(min(values)),
            'max': float(max(values)),
            'mean': float(statistics.mean(values)),
            'std': float(statistics.stdev(values)) if len(values) > 1 else 0.0,
            'median': float(statistics.median(values))
        }
        
    def _calculate_stability_score(self, cpu_stats: Dict[str, float], memory_stats: Dict[str, float]) -> float:
        """Calculate overall system stability score (0-1, higher is better)."""
        if not cpu_stats or not memory_stats:
            return 0.0
            
        # Lower variance = higher stability
        cpu_stability = max(0.0, 1.0 - (cpu_stats.get('std', 100.0) / 100.0))
        memory_stability = max(0.0, 1.0 - (memory_stats.get('std', 100.0) / 100.0))
        
        # Lower absolute values = higher stability (for idle baseline)
        cpu_usage_score = max(0.0, 1.0 - (cpu_stats.get('mean', 100.0) / 100.0))
        memory_usage_score = max(0.0, 1.0 - (memory_stats.get('mean', 100.0) / 100.0))
        
        # Combined score
        stability_score = (cpu_stability * 0.3 + memory_stability * 0.2 + 
                         cpu_usage_score * 0.3 + memory_usage_score * 0.2)
        
        return min(1.0, max(0.0, stability_score))
        
    def _determine_measurement_quality(self, stability_score: float, duration: float, sample_count: int) -> str:
        """Determine overall measurement quality."""
        min_duration = 60.0  # Minimum 1 minute for good quality
        min_samples = 30     # Minimum samples for good quality
        
        if stability_score >= 0.9 and duration >= min_duration * 3 and sample_count >= min_samples * 3:
            return 'excellent'
        elif stability_score >= 0.8 and duration >= min_duration and sample_count >= min_samples:
            return 'good'
        elif stability_score >= 0.6 and duration >= min_duration * 0.5:
            return 'fair'
        else:
            return 'poor'
            
    def _generate_warnings(self, cpu_stats: Dict[str, float], memory_stats: Dict[str, float], stability_score: float) -> List[str]:
        """Generate warnings based on baseline measurement."""
        warnings = []
        
        if not self.idle_validated:
            warnings.append("System idle state was not validated before measurement")
            
        if cpu_stats.get('mean', 0) > 20.0:
            warnings.append(f"High CPU usage during baseline: {cpu_stats['mean']:.1f}%")
            
        if memory_stats.get('mean', 0) > 70.0:
            warnings.append(f"High memory usage during baseline: {memory_stats['mean']:.1f}%")
            
        if stability_score < self.get_parameter('stability_threshold').value:
            warnings.append(f"Low system stability score: {stability_score:.3f}")
            
        if len(self.system_metrics_history) < 30:
            warnings.append("Insufficient data points collected for reliable baseline")
            
        return warnings
        
    def _publish_status(self, status: str):
        """Publish baseline measurement status."""
        try:
            status_data = {
                'status': status,
                'timestamp': time.time(),
                'measurement_duration': self.get_parameter('measurement_duration').value,
                'idle_validated': self.idle_validated
            }
            
            msg = String()
            msg.data = json.dumps(status_data)
            self.baseline_status_pub.publish(msg)
            
        except Exception as e:
            self.get_logger().error(f"Failed to publish status: {e}")
            
    def _publish_current_metrics(self, system_metrics: Optional[BaselineSystemMetrics], 
                                message_metrics: Optional[BaselineMessageMetrics]):
        """Publish current baseline metrics."""
        try:
            metrics_data = {
                'timestamp': time.time(),
                'system': asdict(system_metrics) if system_metrics else None,
                'message': asdict(message_metrics) if message_metrics else None
            }
            
            msg = String()
            msg.data = json.dumps(metrics_data, default=str)
            self.baseline_metrics_pub.publish(msg)
            
        except Exception as e:
            self.get_logger().debug(f"Failed to publish metrics: {e}")
            
    def _publish_baseline_summary(self):
        """Publish completed baseline summary."""
        if self.current_baseline:
            try:
                summary_data = asdict(self.current_baseline)
                
                msg = String()
                msg.data = json.dumps(summary_data, default=str)
                self.baseline_metrics_pub.publish(msg)
                
            except Exception as e:
                self.get_logger().error(f"Failed to publish baseline summary: {e}")
                
    def save_baseline_to_file(self) -> bool:
        """Save current baseline to file."""
        if not self.current_baseline:
            return False
            
        try:
            baseline_file = self.get_parameter('baseline_file').value
            baseline_data = asdict(self.current_baseline)
            baseline_data['saved_timestamp'] = time.time()
            baseline_data['node_info'] = self.system_info
            
            with open(baseline_file, 'w') as f:
                json.dump(baseline_data, f, indent=2, default=str)
                
            self.get_logger().info(f"Baseline saved to {baseline_file}")
            return True
            
        except Exception as e:
            self.get_logger().error(f"Failed to save baseline: {e}")
            return False
            
    def _load_existing_baseline(self):
        """Load existing baseline from file if available."""
        try:
            baseline_file = self.get_parameter('baseline_file').value
            if os.path.exists(baseline_file):
                with open(baseline_file, 'r') as f:
                    baseline_data = json.load(f)
                    
                # Convert back to BaselineSummary (simplified loading)
                self.current_baseline = BaselineSummary(**{
                    k: v for k, v in baseline_data.items() 
                    if k in BaselineSummary.__annotations__
                })
                
                saved_time = baseline_data.get('saved_timestamp', 0)
                age_hours = (time.time() - saved_time) / 3600.0
                
                self.get_logger().info(f"Loaded existing baseline from {baseline_file}")
                self.get_logger().info(f"  Baseline age: {age_hours:.1f} hours")
                self.get_logger().info(f"  Quality: {self.current_baseline.measurement_quality}")
                
            else:
                self.get_logger().info(f"No existing baseline file: {baseline_file}")
                
        except Exception as e:
            self.get_logger().error(f"Failed to load existing baseline: {e}")
            
    def _stress_metrics_callback(self, msg):
        """Monitor for active stress testing that would interfere with baseline."""
        if self.is_measuring:
            try:
                metrics_data = json.loads(msg.data)
                
                # Check if there's significant stress activity
                total_throughput = metrics_data.get('total_throughput_hz', 0)
                if total_throughput > 100:  # High message rate indicates stress testing
                    self.get_logger().warn(f"Stress testing detected during baseline measurement: {total_throughput:.1f} Hz")
                    
            except Exception as e:
                self.get_logger().debug(f"Error processing stress metrics: {e}")
                
    def get_current_baseline(self) -> Optional[BaselineSummary]:
        """Get the current baseline summary."""
        return self.current_baseline
        
    def compare_with_baseline(self, current_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Compare current metrics with baseline."""
        if not self.current_baseline:
            return {'error': 'No baseline available for comparison'}
            
        comparison = {
            'baseline_available': True,
            'baseline_age_hours': (time.time() - self.current_baseline.measurement_start) / 3600.0,
            'baseline_quality': self.current_baseline.measurement_quality,
            'comparisons': {}
        }
        
        # Compare CPU usage
        if 'cpu_percent' in current_metrics:
            baseline_cpu = self.current_baseline.cpu_baseline.get('mean', 0)
            current_cpu = current_metrics['cpu_percent']
            comparison['comparisons']['cpu'] = {
                'baseline': baseline_cpu,
                'current': current_cpu,
                'change_percent': ((current_cpu - baseline_cpu) / max(baseline_cpu, 0.1)) * 100,
                'status': 'elevated' if current_cpu > baseline_cpu * 1.5 else 'normal'
            }
            
        # Compare memory usage
        if 'memory_percent' in current_metrics:
            baseline_memory = self.current_baseline.memory_baseline.get('mean', 0)
            current_memory = current_metrics['memory_percent']
            comparison['comparisons']['memory'] = {
                'baseline': baseline_memory,
                'current': current_memory,
                'change_percent': ((current_memory - baseline_memory) / max(baseline_memory, 0.1)) * 100,
                'status': 'elevated' if current_memory > baseline_memory * 1.3 else 'normal'
            }
            
        return comparison
        
    def destroy_node(self):
        """Clean up resources."""
        if self.is_measuring:
            self.stop_baseline_measurement()
        super().destroy_node()


def main(args=None):
    """Main entry point for baseline collector."""
    rclpy.init(args=args)
    
    try:
        baseline_node = BaselineCollector()
        rclpy.spin(baseline_node)
        
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'baseline_node' in locals():
            baseline_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()