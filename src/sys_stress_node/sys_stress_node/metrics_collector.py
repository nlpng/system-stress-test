#!/usr/bin/env python3
"""
Metrics Collector Node

Central aggregation and analysis system for ROS 2 stress test metrics.
Collects data from multiple sources, performs statistical analysis, and provides
comprehensive performance monitoring and reporting capabilities.
"""

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_msgs.msg import String, Float64, Int64
from geometry_msgs.msg import Twist
import json
import csv
import time
import statistics
import threading
import psutil
import os
from collections import defaultdict, deque
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import numpy as np


@dataclass
class MetricsSnapshot:
    """Data structure for a metrics snapshot at a point in time."""
    timestamp: float
    topic_name: str
    message_count: int
    latency_stats: Dict[str, float]
    throughput_hz: float
    loss_rate: float
    duplicate_rate: float
    bytes_received: int
    callback_time_ms: float


@dataclass
class SystemSnapshot:
    """Data structure for system resource snapshot."""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    memory_available_mb: float
    network_bytes_sent: int
    network_bytes_recv: int
    disk_io_read: int
    disk_io_write: int
    load_average: float


@dataclass
class AggregatedMetrics:
    """Data structure for aggregated metrics across all topics."""
    timestamp: float
    total_messages: int
    total_throughput_hz: float
    average_latency_ms: float
    max_latency_ms: float
    overall_loss_rate: float
    active_topics: int
    system_metrics: SystemSnapshot


class MetricsCollector(Node):
    """Central metrics collection and analysis node."""
    
    def __init__(self):
        super().__init__('metrics_collector')
        
        # Declare parameters
        self.declare_parameter('collection_interval', 1.0)
        self.declare_parameter('retention_period', 3600.0)
        self.declare_parameter('aggregation_window', 60.0)
        self.declare_parameter('baseline_file', 'baseline_metrics.json')
        self.declare_parameter('export_csv', True)
        self.declare_parameter('csv_filename', 'aggregated_metrics.csv')
        self.declare_parameter('alert_latency_threshold', 100.0)
        self.declare_parameter('alert_loss_threshold', 0.05)
        self.declare_parameter('alert_throughput_threshold', 0.8)
        self.declare_parameter('enable_system_monitoring', True)
        self.declare_parameter('enable_trend_analysis', True)
        self.declare_parameter('publisher_topics', ['stress_test_topic'])
        self.declare_parameter('subscriber_topics', ['stress_test_topic'])
        
        # Initialize data storage
        self.metrics_history = deque(maxlen=int(self.get_parameter('retention_period').value))
        self.system_history = deque(maxlen=int(self.get_parameter('retention_period').value))
        self.aggregated_history = deque(maxlen=int(self.get_parameter('retention_period').value))
        
        # Current metrics state
        self.current_metrics = defaultdict(dict)
        self.last_collection_time = time.time()
        self.baseline_metrics = None
        
        # Thread safety
        self.metrics_lock = threading.Lock()
        
        # Statistics tracking
        self.total_messages_processed = 0
        self.collection_start_time = time.time()
        
        # Setup subscribers for metrics data
        self._setup_metrics_subscribers()
        
        # Setup publishers for aggregated metrics
        self._setup_metrics_publishers()
        
        # Setup collection timer
        collection_interval = self.get_parameter('collection_interval').value
        self.collection_timer = self.create_timer(collection_interval, self._collect_metrics)
        
        # Setup analysis timer (less frequent)
        self.analysis_timer = self.create_timer(10.0, self._perform_analysis)
        
        # Setup CSV export
        if self.get_parameter('export_csv').value:
            self._setup_csv_export()
        
        # Load baseline if available
        self._load_baseline_metrics()
        
        # System monitoring setup
        if self.get_parameter('enable_system_monitoring').value:
            self._setup_system_monitoring()
        
        self.get_logger().info("MetricsCollector initialized")
        self.get_logger().info(f"  Collection interval: {collection_interval}s")
        self.get_logger().info(f"  Retention period: {self.get_parameter('retention_period').value}s")
        self.get_logger().info(f"  Monitoring topics: {self.get_parameter('subscriber_topics').value}")
        
    def _setup_metrics_subscribers(self):
        """Setup subscribers to collect metrics from stress test nodes."""
        # Subscribe to metrics topics (these would be published by stress test nodes)
        self.metrics_subscriber = self.create_subscription(
            String, 'stress_test_metrics', self._metrics_callback, 10
        )
        
        # Subscribe to publisher statistics
        self.publisher_stats_subscriber = self.create_subscription(
            String, 'publisher_statistics', self._publisher_stats_callback, 10
        )
        
        # Subscribe to subscriber statistics  
        self.subscriber_stats_subscriber = self.create_subscription(
            String, 'subscriber_statistics', self._subscriber_stats_callback, 10
        )
        
    def _setup_metrics_publishers(self):
        """Setup publishers for aggregated metrics and alerts."""
        # Publish aggregated metrics
        self.aggregated_metrics_pub = self.create_publisher(
            String, 'aggregated_metrics', 10
        )
        
        # Publish performance alerts
        self.alerts_pub = self.create_publisher(
            String, 'performance_alerts', 10
        )
        
        # Publish system health status
        self.health_status_pub = self.create_publisher(
            String, 'system_health', 10
        )
        
        # Publish analysis reports
        self.analysis_report_pub = self.create_publisher(
            String, 'analysis_report', 10
        )
        
    def _setup_system_monitoring(self):
        """Setup system resource monitoring."""
        try:
            # Initialize psutil for system monitoring
            self.process = psutil.Process()
            self.system_info = {
                'cpu_count': psutil.cpu_count(),
                'memory_total': psutil.virtual_memory().total,
                'boot_time': psutil.boot_time()
            }
            self.get_logger().info(f"System monitoring enabled: {self.system_info['cpu_count']} CPUs, {self.system_info['memory_total']//1024//1024//1024} GB RAM")
        except Exception as e:
            self.get_logger().error(f"Failed to setup system monitoring: {e}")
            
    def _collect_system_metrics(self) -> SystemSnapshot:
        """Collect current system resource metrics."""
        try:
            # CPU and memory
            cpu_percent = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            
            # Network I/O
            network = psutil.net_io_counters()
            
            # Disk I/O
            disk = psutil.disk_io_counters()
            
            # Load average
            load_avg = psutil.getloadavg()[0] if hasattr(psutil, 'getloadavg') else 0.0
            
            return SystemSnapshot(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_available_mb=memory.available / 1024 / 1024,
                network_bytes_sent=network.bytes_sent if network else 0,
                network_bytes_recv=network.bytes_recv if network else 0,
                disk_io_read=disk.read_bytes if disk else 0,
                disk_io_write=disk.write_bytes if disk else 0,
                load_average=load_avg
            )
        except Exception as e:
            self.get_logger().debug(f"Error collecting system metrics: {e}")
            return SystemSnapshot(
                timestamp=time.time(),
                cpu_percent=0.0, memory_percent=0.0, memory_available_mb=0.0,
                network_bytes_sent=0, network_bytes_recv=0,
                disk_io_read=0, disk_io_write=0, load_average=0.0
            )
    
    def _metrics_callback(self, msg):
        """Handle incoming metrics data."""
        try:
            metrics_data = json.loads(msg.data)
            topic_name = metrics_data.get('topic', 'unknown')
            
            with self.metrics_lock:
                self.current_metrics[topic_name] = metrics_data
                self.total_messages_processed += metrics_data.get('message_count', 0)
                
        except json.JSONDecodeError as e:
            self.get_logger().debug(f"Invalid JSON in metrics: {e}")
        except Exception as e:
            self.get_logger().error(f"Error processing metrics: {e}")
            
    def _publisher_stats_callback(self, msg):
        """Handle publisher statistics."""
        try:
            stats_data = json.loads(msg.data)
            # Store publisher-specific statistics
            with self.metrics_lock:
                self.current_metrics[f"publisher_{stats_data.get('topic', 'unknown')}"] = stats_data
        except Exception as e:
            self.get_logger().debug(f"Error processing publisher stats: {e}")
            
    def _subscriber_stats_callback(self, msg):
        """Handle subscriber statistics."""
        try:
            stats_data = json.loads(msg.data)
            # Store subscriber-specific statistics
            with self.metrics_lock:
                self.current_metrics[f"subscriber_{stats_data.get('topic', 'unknown')}"] = stats_data
        except Exception as e:
            self.get_logger().debug(f"Error processing subscriber stats: {e}")
            
    def _collect_metrics(self):
        """Main metrics collection and aggregation function."""
        current_time = time.time()
        
        # Collect system metrics
        system_snapshot = None
        if self.get_parameter('enable_system_monitoring').value:
            system_snapshot = self._collect_system_metrics()
            self.system_history.append(system_snapshot)
        
        # Aggregate current metrics
        with self.metrics_lock:
            aggregated = self._aggregate_current_metrics(current_time, system_snapshot)
            
            if aggregated:
                self.aggregated_history.append(aggregated)
                
                # Publish aggregated metrics
                self._publish_aggregated_metrics(aggregated)
                
                # Check for alerts
                self._check_performance_alerts(aggregated)
                
                # Export to CSV if enabled
                if self.get_parameter('export_csv').value:
                    self._export_to_csv(aggregated)
                    
                # Clean old data
                self._cleanup_old_data(current_time)
                
        self.last_collection_time = current_time
        
    def _aggregate_current_metrics(self, timestamp: float, system_snapshot: SystemSnapshot) -> Optional[AggregatedMetrics]:
        """Aggregate current metrics from all sources."""
        if not self.current_metrics:
            return None
            
        total_messages = 0
        total_throughput = 0.0
        latency_values = []
        max_latency = 0.0
        loss_rates = []
        active_topics = 0
        
        for topic_name, metrics in self.current_metrics.items():
            if isinstance(metrics, dict) and 'message_count' in metrics:
                active_topics += 1
                total_messages += metrics.get('message_count', 0)
                total_throughput += metrics.get('throughput_hz', 0.0)
                
                # Collect latency data
                latency_stats = metrics.get('latency_stats', {})
                if latency_stats:
                    avg_latency = latency_stats.get('avg', 0.0)
                    if avg_latency > 0:
                        latency_values.append(avg_latency)
                    max_latency = max(max_latency, latency_stats.get('max', 0.0))
                
                # Collect loss rates
                loss_rate = metrics.get('loss_rate', 0.0)
                if loss_rate >= 0:
                    loss_rates.append(loss_rate)
        
        # Calculate aggregated statistics
        average_latency = statistics.mean(latency_values) if latency_values else 0.0
        overall_loss_rate = statistics.mean(loss_rates) if loss_rates else 0.0
        
        return AggregatedMetrics(
            timestamp=timestamp,
            total_messages=total_messages,
            total_throughput_hz=total_throughput,
            average_latency_ms=average_latency,
            max_latency_ms=max_latency,
            overall_loss_rate=overall_loss_rate,
            active_topics=active_topics,
            system_metrics=system_snapshot
        )
        
    def _publish_aggregated_metrics(self, metrics: AggregatedMetrics):
        """Publish aggregated metrics to ROS 2 topic."""
        try:
            metrics_dict = asdict(metrics)
            # Handle nested dataclass
            if metrics.system_metrics:
                metrics_dict['system_metrics'] = asdict(metrics.system_metrics)
                
            msg = String()
            msg.data = json.dumps(metrics_dict, default=str)
            self.aggregated_metrics_pub.publish(msg)
            
        except Exception as e:
            self.get_logger().error(f"Failed to publish aggregated metrics: {e}")
            
    def _check_performance_alerts(self, metrics: AggregatedMetrics):
        """Check for performance issues and publish alerts."""
        alerts = []
        
        # Check latency threshold
        latency_threshold = self.get_parameter('alert_latency_threshold').value
        if metrics.average_latency_ms > latency_threshold:
            alerts.append({
                'type': 'high_latency',
                'severity': 'warning',
                'message': f"Average latency {metrics.average_latency_ms:.2f}ms exceeds threshold {latency_threshold}ms",
                'value': metrics.average_latency_ms,
                'threshold': latency_threshold
            })
        
        # Check loss rate threshold
        loss_threshold = self.get_parameter('alert_loss_threshold').value
        if metrics.overall_loss_rate > loss_threshold:
            alerts.append({
                'type': 'high_loss_rate',
                'severity': 'error',
                'message': f"Message loss rate {metrics.overall_loss_rate:.2%} exceeds threshold {loss_threshold:.2%}",
                'value': metrics.overall_loss_rate,
                'threshold': loss_threshold
            })
        
        # Check system resource alerts
        if metrics.system_metrics:
            if metrics.system_metrics.cpu_percent > 90.0:
                alerts.append({
                    'type': 'high_cpu',
                    'severity': 'warning',
                    'message': f"CPU usage {metrics.system_metrics.cpu_percent:.1f}% is very high",
                    'value': metrics.system_metrics.cpu_percent
                })
                
            if metrics.system_metrics.memory_percent > 90.0:
                alerts.append({
                    'type': 'high_memory',
                    'severity': 'warning',
                    'message': f"Memory usage {metrics.system_metrics.memory_percent:.1f}% is very high",
                    'value': metrics.system_metrics.memory_percent
                })
        
        # Publish alerts
        if alerts:
            for alert in alerts:
                self._publish_alert(alert)
                
    def _publish_alert(self, alert: Dict[str, Any]):
        """Publish a performance alert."""
        try:
            alert['timestamp'] = time.time()
            msg = String()
            msg.data = json.dumps(alert)
            self.alerts_pub.publish(msg)
            
            # Also log the alert
            severity = alert['severity'].upper()
            self.get_logger().warn(f"[{severity}] {alert['message']}")
            
        except Exception as e:
            self.get_logger().error(f"Failed to publish alert: {e}")
            
    def _perform_analysis(self):
        """Perform periodic analysis and publish reports."""
        if not self.get_parameter('enable_trend_analysis').value:
            return
            
        try:
            analysis_report = self._generate_analysis_report()
            if analysis_report:
                self._publish_analysis_report(analysis_report)
                
        except Exception as e:
            self.get_logger().error(f"Error performing analysis: {e}")
            
    def _generate_analysis_report(self) -> Optional[Dict[str, Any]]:
        """Generate comprehensive analysis report."""
        if len(self.aggregated_history) < 10:  # Need sufficient data
            return None
            
        current_time = time.time()
        window_size = self.get_parameter('aggregation_window').value
        
        # Get recent data within analysis window
        recent_data = [m for m in self.aggregated_history 
                      if current_time - m.timestamp <= window_size]
        
        if not recent_data:
            return None
            
        # Calculate trends
        latencies = [m.average_latency_ms for m in recent_data]
        throughputs = [m.total_throughput_hz for m in recent_data]
        loss_rates = [m.overall_loss_rate for m in recent_data]
        
        report = {
            'timestamp': current_time,
            'analysis_window_seconds': window_size,
            'data_points': len(recent_data),
            'trends': {
                'latency': self._calculate_trend(latencies),
                'throughput': self._calculate_trend(throughputs),
                'loss_rate': self._calculate_trend(loss_rates)
            },
            'summary': {
                'avg_latency_ms': statistics.mean(latencies) if latencies else 0,
                'avg_throughput_hz': statistics.mean(throughputs) if throughputs else 0,
                'avg_loss_rate': statistics.mean(loss_rates) if loss_rates else 0,
                'max_latency_ms': max(latencies) if latencies else 0,
                'min_throughput_hz': min(throughputs) if throughputs else 0
            }
        }
        
        # Compare with baseline if available
        if self.baseline_metrics:
            report['baseline_comparison'] = self._compare_with_baseline(report['summary'])
            
        return report
        
    def _calculate_trend(self, values: List[float]) -> Dict[str, Any]:
        """Calculate trend information for a series of values."""
        if len(values) < 3:
            return {'direction': 'insufficient_data', 'slope': 0.0, 'confidence': 0.0}
            
        # Simple linear regression for trend
        x = list(range(len(values)))
        n = len(values)
        
        sum_x = sum(x)
        sum_y = sum(values)
        sum_xy = sum(x[i] * values[i] for i in range(n))
        sum_x2 = sum(xi ** 2 for xi in x)
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x ** 2)
        
        # Determine trend direction
        if abs(slope) < 0.01:  # Threshold for "stable"
            direction = 'stable'
        elif slope > 0:
            direction = 'increasing'
        else:
            direction = 'decreasing'
            
        # Simple confidence based on variance
        variance = statistics.variance(values) if len(values) > 1 else 0
        confidence = min(1.0, abs(slope) / (variance + 0.001))
        
        return {
            'direction': direction,
            'slope': slope,
            'confidence': confidence,
            'variance': variance
        }
        
    def _compare_with_baseline(self, current_summary: Dict[str, float]) -> Dict[str, Any]:
        """Compare current metrics with baseline."""
        comparison = {}
        
        for metric, current_value in current_summary.items():
            baseline_value = self.baseline_metrics.get(metric, 0)
            if baseline_value > 0:
                change_percent = ((current_value - baseline_value) / baseline_value) * 100
                comparison[metric] = {
                    'current': current_value,
                    'baseline': baseline_value,
                    'change_percent': change_percent,
                    'improved': self._is_improvement(metric, change_percent)
                }
                
        return comparison
        
    def _is_improvement(self, metric: str, change_percent: float) -> bool:
        """Determine if a change represents an improvement."""
        # Lower is better for latency and loss rate
        if 'latency' in metric or 'loss' in metric:
            return change_percent < 0
        # Higher is better for throughput
        elif 'throughput' in metric:
            return change_percent > 0
        else:
            return False
            
    def _publish_analysis_report(self, report: Dict[str, Any]):
        """Publish analysis report."""
        try:
            msg = String()
            msg.data = json.dumps(report, default=str)
            self.analysis_report_pub.publish(msg)
            
            # Log key findings
            summary = report['summary']
            self.get_logger().info(f"Analysis Report: Avg latency: {summary['avg_latency_ms']:.2f}ms, "
                                 f"Avg throughput: {summary['avg_throughput_hz']:.2f}Hz, "
                                 f"Avg loss rate: {summary['avg_loss_rate']:.4f}")
            
        except Exception as e:
            self.get_logger().error(f"Failed to publish analysis report: {e}")
            
    def _setup_csv_export(self):
        """Setup CSV export for metrics."""
        try:
            csv_filename = self.get_parameter('csv_filename').value
            self.csv_file = open(csv_filename, 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            
            # Write header
            header = [
                'timestamp', 'total_messages', 'total_throughput_hz', 'average_latency_ms',
                'max_latency_ms', 'overall_loss_rate', 'active_topics',
                'cpu_percent', 'memory_percent', 'memory_available_mb', 'load_average'
            ]
            self.csv_writer.writerow(header)
            self.csv_file.flush()
            
            self.get_logger().info(f"CSV export enabled: {csv_filename}")
            
        except Exception as e:
            self.get_logger().error(f"Failed to setup CSV export: {e}")
            
    def _export_to_csv(self, metrics: AggregatedMetrics):
        """Export metrics to CSV file."""
        try:
            row = [
                metrics.timestamp, metrics.total_messages, metrics.total_throughput_hz,
                metrics.average_latency_ms, metrics.max_latency_ms, metrics.overall_loss_rate,
                metrics.active_topics
            ]
            
            # Add system metrics if available
            if metrics.system_metrics:
                row.extend([
                    metrics.system_metrics.cpu_percent,
                    metrics.system_metrics.memory_percent,
                    metrics.system_metrics.memory_available_mb,
                    metrics.system_metrics.load_average
                ])
            else:
                row.extend([0, 0, 0, 0])
                
            self.csv_writer.writerow(row)
            
            # Flush periodically
            if len(self.aggregated_history) % 60 == 0:  # Every minute
                self.csv_file.flush()
                
        except Exception as e:
            self.get_logger().error(f"Failed to export to CSV: {e}")
            
    def _load_baseline_metrics(self):
        """Load baseline metrics from file."""
        try:
            baseline_file = self.get_parameter('baseline_file').value
            if os.path.exists(baseline_file):
                with open(baseline_file, 'r') as f:
                    self.baseline_metrics = json.load(f)
                self.get_logger().info(f"Loaded baseline metrics from {baseline_file}")
            else:
                self.get_logger().info(f"No baseline file found: {baseline_file}")
        except Exception as e:
            self.get_logger().error(f"Failed to load baseline metrics: {e}")
            
    def save_baseline_metrics(self):
        """Save current metrics as baseline."""
        try:
            if not self.aggregated_history:
                self.get_logger().warn("No metrics data to save as baseline")
                return
                
            # Use recent average as baseline
            recent_data = list(self.aggregated_history)[-60:]  # Last 60 data points
            
            baseline = {
                'avg_latency_ms': statistics.mean([m.average_latency_ms for m in recent_data]),
                'avg_throughput_hz': statistics.mean([m.total_throughput_hz for m in recent_data]),
                'avg_loss_rate': statistics.mean([m.overall_loss_rate for m in recent_data]),
                'timestamp': time.time(),
                'data_points': len(recent_data)
            }
            
            baseline_file = self.get_parameter('baseline_file').value
            with open(baseline_file, 'w') as f:
                json.dump(baseline, f, indent=2)
                
            self.baseline_metrics = baseline
            self.get_logger().info(f"Saved baseline metrics to {baseline_file}")
            
        except Exception as e:
            self.get_logger().error(f"Failed to save baseline metrics: {e}")
            
    def _cleanup_old_data(self, current_time: float):
        """Clean up old data beyond retention period."""
        retention_period = self.get_parameter('retention_period').value
        cutoff_time = current_time - retention_period
        
        # Clean aggregated history
        while self.aggregated_history and self.aggregated_history[0].timestamp < cutoff_time:
            self.aggregated_history.popleft()
            
        # Clean system history
        while self.system_history and self.system_history[0].timestamp < cutoff_time:
            self.system_history.popleft()
            
    def get_comprehensive_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics for the entire collection period."""
        current_time = time.time()
        runtime = current_time - self.collection_start_time
        
        stats = {
            'collection_runtime_seconds': runtime,
            'total_data_points': len(self.aggregated_history),
            'data_collection_rate': len(self.aggregated_history) / runtime if runtime > 0 else 0,
            'total_messages_processed': self.total_messages_processed
        }
        
        if self.aggregated_history:
            recent_metrics = list(self.aggregated_history)
            stats['recent_performance'] = {
                'avg_latency_ms': statistics.mean([m.average_latency_ms for m in recent_metrics]),
                'avg_throughput_hz': statistics.mean([m.total_throughput_hz for m in recent_metrics]),
                'avg_loss_rate': statistics.mean([m.overall_loss_rate for m in recent_metrics]),
                'max_latency_ms': max([m.max_latency_ms for m in recent_metrics]),
                'peak_throughput_hz': max([m.total_throughput_hz for m in recent_metrics])
            }
            
        return stats
        
    def destroy_node(self):
        """Clean up resources."""
        if hasattr(self, 'csv_file'):
            try:
                self.csv_file.close()
            except:
                pass
        super().destroy_node()


def main(args=None):
    """Main entry point for metrics collector."""
    rclpy.init(args=args)
    
    try:
        collector_node = MetricsCollector()
        
        # Log statistics periodically
        def log_comprehensive_stats():
            stats = collector_node.get_comprehensive_statistics()
            collector_node.get_logger().info(f"MetricsCollector Stats: {stats}")
            
        stats_timer = collector_node.create_timer(30.0, log_comprehensive_stats)
        
        rclpy.spin(collector_node)
        
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'collector_node' in locals():
            collector_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()