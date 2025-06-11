#!/usr/bin/env python3
"""
Message Stress Subscriber Node

ROS 2 subscriber for measuring message latency, throughput, and loss rates during stress testing.
Provides comprehensive metrics collection and analysis for message communication performance.
"""

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from std_msgs.msg import String, ByteMultiArray
from geometry_msgs.msg import Twist
import time
import json
import csv
import threading
import statistics
from collections import defaultdict, deque
from typing import Dict, List, Any, Optional, Tuple
import re


class MessageStressSubscriber(Node):
    """ROS 2 node for measuring message stress test performance."""
    
    def __init__(self):
        super().__init__('message_stress_subscriber')
        
        # Declare parameters
        self.declare_parameter('topic_names', ['stress_test_topic'])
        self.declare_parameter('expected_rate', 10.0)
        self.declare_parameter('latency_percentiles', [50, 90, 95, 99])
        self.declare_parameter('statistics_window', 1000)
        self.declare_parameter('qos_reliability', 'reliable')
        self.declare_parameter('qos_durability', 'volatile')
        self.declare_parameter('qos_history', 'keep_last')
        self.declare_parameter('qos_depth', 10)
        self.declare_parameter('log_interval', 10.0)
        self.declare_parameter('latency_threshold_ms', 100.0)
        self.declare_parameter('loss_rate_threshold', 0.05)
        self.declare_parameter('export_csv', False)
        self.declare_parameter('csv_filename', 'stress_test_metrics.csv')
        
        # Initialize metrics storage
        self.metrics = defaultdict(lambda: {
            'latency_data': deque(maxlen=self.get_parameter('statistics_window').value),
            'arrival_times': deque(maxlen=self.get_parameter('statistics_window').value),
            'sequence_numbers': deque(maxlen=self.get_parameter('statistics_window').value),
            'callback_times': deque(maxlen=self.get_parameter('statistics_window').value),
            'message_count': 0,
            'last_sequence': -1,
            'expected_sequence': 0,
            'lost_messages': 0,
            'duplicate_messages': 0,
            'first_message_time': None,
            'last_message_time': None,
            'total_bytes_received': 0
        })
        
        # Global statistics
        self.start_time = time.time()
        self.total_messages = 0
        self.subscribers = {}
        
        # Thread safety
        self.metrics_lock = threading.Lock()
        
        # Setup subscribers
        self._setup_subscribers()
        
        # Setup statistics logging timer
        log_interval = self.get_parameter('log_interval').value
        self.stats_timer = self.create_timer(log_interval, self._log_statistics)
        
        # CSV export setup
        if self.get_parameter('export_csv').value:
            self._setup_csv_export()
        
        # Parameter callback
        self.add_on_set_parameters_callback(self._parameter_callback)
        
        self.get_logger().info(f"MessageStressSubscriber initialized")
        self.get_logger().info(f"  Topics: {self.get_parameter('topic_names').value}")
        self.get_logger().info(f"  Expected rate: {self.get_parameter('expected_rate').value} Hz")
        self.get_logger().info(f"  Statistics window: {self.get_parameter('statistics_window').value}")
        
    def _setup_subscribers(self):
        """Setup subscribers for all configured topics."""
        topic_names = self.get_parameter('topic_names').value
        
        # Get QoS parameters
        reliability = self.get_parameter('qos_reliability').value
        durability = self.get_parameter('qos_durability').value
        history = self.get_parameter('qos_history').value
        depth = self.get_parameter('qos_depth').value
        
        # Configure QoS profile
        qos_profile = QoSProfile(depth=depth)
        
        if reliability == 'reliable':
            qos_profile.reliability = ReliabilityPolicy.RELIABLE
        else:
            qos_profile.reliability = ReliabilityPolicy.BEST_EFFORT
            
        if durability == 'transient_local':
            qos_profile.durability = DurabilityPolicy.TRANSIENT_LOCAL
        else:
            qos_profile.durability = DurabilityPolicy.VOLATILE
            
        if history == 'keep_all':
            qos_profile.history = HistoryPolicy.KEEP_ALL
        else:
            qos_profile.history = HistoryPolicy.KEEP_LAST
        
        # Create subscribers for each topic
        for topic_name in topic_names:
            # Try to determine message type from topic name or use multiple subscribers
            self._create_topic_subscribers(topic_name, qos_profile)
            
    def _create_topic_subscribers(self, topic_name: str, qos_profile: QoSProfile):
        """Create subscribers for different message types on a topic."""
        # Create callback with topic name
        string_callback = lambda msg, topic=topic_name: self._message_callback(msg, topic, 'string')
        bytes_callback = lambda msg, topic=topic_name: self._message_callback(msg, topic, 'bytes')
        twist_callback = lambda msg, topic=topic_name: self._message_callback(msg, topic, 'twist')
        
        # Create subscribers for different message types
        # In practice, you'd know the message type, but this handles multiple types
        try:
            string_sub = self.create_subscription(String, topic_name, string_callback, qos_profile)
            self.subscribers[f"{topic_name}_string"] = string_sub
        except Exception as e:
            self.get_logger().debug(f"Could not create String subscriber for {topic_name}: {e}")
            
        try:
            bytes_sub = self.create_subscription(ByteMultiArray, topic_name, bytes_callback, qos_profile)
            self.subscribers[f"{topic_name}_bytes"] = bytes_sub
        except Exception as e:
            self.get_logger().debug(f"Could not create ByteMultiArray subscriber for {topic_name}: {e}")
            
        try:
            twist_sub = self.create_subscription(Twist, topic_name, twist_callback, qos_profile)
            self.subscribers[f"{topic_name}_twist"] = twist_sub
        except Exception as e:
            self.get_logger().debug(f"Could not create Twist subscriber for {topic_name}: {e}")
            
    def _message_callback(self, msg, topic_name: str, msg_type: str):
        """Handle incoming messages and collect metrics."""
        callback_start = time.time()
        receive_time = time.time_ns()
        
        try:
            # Extract timestamp and sequence number from message
            timestamp_ns, sequence_num, payload_size = self._extract_message_info(msg, msg_type)
            
            if timestamp_ns is not None:
                # Calculate latency
                latency_ns = receive_time - timestamp_ns
                latency_ms = latency_ns / 1_000_000.0
                
                with self.metrics_lock:
                    topic_metrics = self.metrics[topic_name]
                    
                    # Update message count and timing
                    topic_metrics['message_count'] += 1
                    self.total_messages += 1
                    
                    if topic_metrics['first_message_time'] is None:
                        topic_metrics['first_message_time'] = receive_time
                    topic_metrics['last_message_time'] = receive_time
                    
                    # Store latency data
                    topic_metrics['latency_data'].append(latency_ms)
                    topic_metrics['arrival_times'].append(receive_time)
                    topic_metrics['total_bytes_received'] += payload_size
                    
                    # Track sequence numbers for loss detection
                    if sequence_num is not None:
                        self._track_sequence_number(topic_metrics, sequence_num)
                    
                    # Store callback execution time
                    callback_end = time.time()
                    callback_duration = (callback_end - callback_start) * 1000.0  # ms
                    topic_metrics['callback_times'].append(callback_duration)
                    
                    # Check for performance alerts
                    self._check_performance_alerts(topic_name, latency_ms)
                    
                    # Export to CSV if enabled
                    if self.get_parameter('export_csv').value:
                        self._export_message_to_csv(topic_name, receive_time, latency_ms, 
                                                  sequence_num, payload_size, msg_type)
                        
        except Exception as e:
            self.get_logger().error(f"Error processing message from {topic_name}: {e}")
            
    def _extract_message_info(self, msg, msg_type: str) -> Tuple[Optional[int], Optional[int], int]:
        """Extract timestamp, sequence number, and payload size from message."""
        timestamp_ns = None
        sequence_num = None
        payload_size = 0
        
        try:
            if msg_type == 'string':
                # Extract from string format: "msg_{seq}_ts_{timestamp}_{data}"
                data = msg.data
                payload_size = len(data.encode('utf-8'))
                
                # Parse timestamp and sequence
                match = re.search(r'msg_(\d+)_ts_(\d+)', data)
                if match:
                    sequence_num = int(match.group(1))
                    timestamp_ns = int(match.group(2))
                    
            elif msg_type == 'bytes':
                # Extract timestamp from first 8 bytes
                if len(msg.data) >= 8:
                    timestamp_bytes = bytes(msg.data[:8])
                    timestamp_ns = int.from_bytes(timestamp_bytes, byteorder='little')
                    payload_size = len(msg.data)
                    # Sequence number could be embedded in next bytes if needed
                    
            elif msg_type == 'twist':
                # Extract timestamp from angular.z field (encoded as float)
                timestamp_float = msg.angular.z
                if timestamp_float != 0.0:
                    # Reconstruct timestamp (this is a simplified approach)
                    timestamp_ns = int(timestamp_float * 1000000) + (int(time.time()) * 1_000_000_000)
                payload_size = 48  # Approximate size of Twist message
                # Sequence could be derived from linear.x if needed
                sequence_num = int(msg.linear.x * 10)  # Reverse the encoding
                
        except Exception as e:
            self.get_logger().debug(f"Could not extract message info: {e}")
            
        return timestamp_ns, sequence_num, payload_size
        
    def _track_sequence_number(self, topic_metrics: Dict, sequence_num: int):
        """Track sequence numbers to detect lost and duplicate messages."""
        if sequence_num is not None:
            topic_metrics['sequence_numbers'].append(sequence_num)
            
            if topic_metrics['last_sequence'] >= 0:
                expected_next = topic_metrics['last_sequence'] + 1
                
                if sequence_num > expected_next:
                    # Detected lost messages
                    lost_count = sequence_num - expected_next
                    topic_metrics['lost_messages'] += lost_count
                    self.get_logger().debug(f"Lost {lost_count} messages, expected {expected_next}, got {sequence_num}")
                    
                elif sequence_num < expected_next:
                    # Detected duplicate or out-of-order message
                    topic_metrics['duplicate_messages'] += 1
                    self.get_logger().debug(f"Duplicate/out-of-order message: {sequence_num}, expected >= {expected_next}")
                    
            topic_metrics['last_sequence'] = max(topic_metrics['last_sequence'], sequence_num)
            
    def _check_performance_alerts(self, topic_name: str, latency_ms: float):
        """Check for performance issues and log alerts."""
        latency_threshold = self.get_parameter('latency_threshold_ms').value
        
        if latency_ms > latency_threshold:
            self.get_logger().warn(f"High latency on {topic_name}: {latency_ms:.2f}ms (threshold: {latency_threshold}ms)")
            
    def _log_statistics(self):
        """Log comprehensive statistics for all topics."""
        with self.metrics_lock:
            current_time = time.time()
            runtime = current_time - self.start_time
            
            self.get_logger().info(f"=== Message Stress Test Statistics (Runtime: {runtime:.1f}s) ===")
            self.get_logger().info(f"Total messages received: {self.total_messages}")
            
            for topic_name, topic_metrics in self.metrics.items():
                if topic_metrics['message_count'] > 0:
                    self._log_topic_statistics(topic_name, topic_metrics, runtime)
                    
    def _log_topic_statistics(self, topic_name: str, topic_metrics: Dict, runtime: float):
        """Log detailed statistics for a specific topic."""
        msg_count = topic_metrics['message_count']
        
        # Calculate rates
        avg_rate = msg_count / runtime if runtime > 0 else 0.0
        expected_rate = self.get_parameter('expected_rate').value
        
        # Calculate latency statistics
        if topic_metrics['latency_data']:
            latencies = list(topic_metrics['latency_data'])
            latency_stats = {
                'min': min(latencies),
                'max': max(latencies),
                'avg': statistics.mean(latencies),
                'median': statistics.median(latencies)
            }
            
            # Calculate percentiles
            percentiles = self.get_parameter('latency_percentiles').value
            for p in percentiles:
                try:
                    latency_stats[f'p{p}'] = statistics.quantiles(latencies, n=100)[p-1]
                except (IndexError, statistics.StatisticsError):
                    latency_stats[f'p{p}'] = 0.0
        else:
            latency_stats = {'min': 0, 'max': 0, 'avg': 0, 'median': 0}
            
        # Calculate loss rate
        total_expected = topic_metrics['expected_sequence'] + 1 if topic_metrics['last_sequence'] >= 0 else msg_count
        loss_rate = topic_metrics['lost_messages'] / max(1, total_expected) * 100.0
        
        # Calculate throughput
        if len(topic_metrics['arrival_times']) >= 2:
            time_span = (topic_metrics['arrival_times'][-1] - topic_metrics['arrival_times'][0]) / 1_000_000_000.0
            instantaneous_rate = (len(topic_metrics['arrival_times']) - 1) / max(0.001, time_span)
        else:
            instantaneous_rate = 0.0
            
        # Log statistics
        self.get_logger().info(f"--- Topic: {topic_name} ---")
        self.get_logger().info(f"  Messages: {msg_count}, Rate: {avg_rate:.2f} Hz (expected: {expected_rate:.2f} Hz)")
        self.get_logger().info(f"  Instantaneous rate: {instantaneous_rate:.2f} Hz")
        self.get_logger().info(f"  Loss rate: {loss_rate:.2f}% ({topic_metrics['lost_messages']} lost, {topic_metrics['duplicate_messages']} duplicates)")
        self.get_logger().info(f"  Latency - min: {latency_stats['min']:.2f}ms, max: {latency_stats['max']:.2f}ms, avg: {latency_stats['avg']:.2f}ms")
        self.get_logger().info(f"  Latency - median: {latency_stats['median']:.2f}ms, p95: {latency_stats.get('p95', 0):.2f}ms")
        self.get_logger().info(f"  Data received: {topic_metrics['total_bytes_received']} bytes")
        
        # Check loss rate threshold
        loss_threshold = self.get_parameter('loss_rate_threshold').value
        if loss_rate > loss_threshold * 100:
            self.get_logger().warn(f"High message loss rate on {topic_name}: {loss_rate:.2f}%")
            
    def _setup_csv_export(self):
        """Setup CSV export for detailed metrics."""
        try:
            csv_filename = self.get_parameter('csv_filename').value
            self.csv_file = open(csv_filename, 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)
            
            # Write header
            header = ['timestamp_ns', 'topic', 'latency_ms', 'sequence_num', 'payload_size', 'message_type']
            self.csv_writer.writerow(header)
            self.csv_file.flush()
            
            self.get_logger().info(f"CSV export enabled: {csv_filename}")
            
        except Exception as e:
            self.get_logger().error(f"Failed to setup CSV export: {e}")
            
    def _export_message_to_csv(self, topic_name: str, timestamp_ns: int, latency_ms: float,
                              sequence_num: Optional[int], payload_size: int, msg_type: str):
        """Export message metrics to CSV file."""
        try:
            row = [timestamp_ns, topic_name, latency_ms, sequence_num, payload_size, msg_type]
            self.csv_writer.writerow(row)
            
            # Flush periodically
            if self.total_messages % 100 == 0:
                self.csv_file.flush()
                
        except Exception as e:
            self.get_logger().error(f"Failed to export to CSV: {e}")
            
    def _parameter_callback(self, params):
        """Handle parameter updates."""
        for param in params:
            if param.name in ['topic_names', 'qos_reliability', 'qos_durability', 'qos_history', 'qos_depth']:
                self.get_logger().info(f"Updating subscriber configuration: {param.name} = {param.value}")
                # Would need to recreate subscribers (complex operation)
                self.get_logger().warn("Subscriber reconfiguration requires node restart")
                
        return rclpy.parameter.SetParametersResult(successful=True)
        
    def get_comprehensive_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics for all topics."""
        with self.metrics_lock:
            current_time = time.time()
            runtime = current_time - self.start_time
            
            stats = {
                'total_messages': self.total_messages,
                'runtime_seconds': runtime,
                'overall_rate': self.total_messages / runtime if runtime > 0 else 0.0,
                'topics': {}
            }
            
            for topic_name, topic_metrics in self.metrics.items():
                if topic_metrics['message_count'] > 0:
                    topic_stats = self._calculate_topic_statistics(topic_metrics, runtime)
                    stats['topics'][topic_name] = topic_stats
                    
            return stats
            
    def _calculate_topic_statistics(self, topic_metrics: Dict, runtime: float) -> Dict[str, Any]:
        """Calculate comprehensive statistics for a topic."""
        msg_count = topic_metrics['message_count']
        
        # Basic stats
        topic_stats = {
            'message_count': msg_count,
            'average_rate': msg_count / runtime if runtime > 0 else 0.0,
            'total_bytes': topic_metrics['total_bytes_received'],
            'lost_messages': topic_metrics['lost_messages'],
            'duplicate_messages': topic_metrics['duplicate_messages']
        }
        
        # Latency statistics
        if topic_metrics['latency_data']:
            latencies = list(topic_metrics['latency_data'])
            topic_stats['latency'] = {
                'min': min(latencies),
                'max': max(latencies),
                'mean': statistics.mean(latencies),
                'median': statistics.median(latencies),
                'std_dev': statistics.stdev(latencies) if len(latencies) > 1 else 0.0
            }
        else:
            topic_stats['latency'] = None
            
        # Loss rate calculation
        total_expected = max(1, topic_metrics['last_sequence'] + 1 if topic_metrics['last_sequence'] >= 0 else msg_count)
        topic_stats['loss_rate'] = topic_metrics['lost_messages'] / total_expected
        
        return topic_stats
        
    def destroy_node(self):
        """Clean up resources."""
        if hasattr(self, 'csv_file'):
            try:
                self.csv_file.close()
            except:
                pass
        super().destroy_node()


def main(args=None):
    """Main entry point for message stress subscriber."""
    rclpy.init(args=args)
    
    try:
        subscriber_node = MessageStressSubscriber()
        rclpy.spin(subscriber_node)
        
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'subscriber_node' in locals():
            subscriber_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()