#!/usr/bin/env python3
"""
Message Stress Publisher Node

Configurable ROS 2 publisher for stress testing message throughput and system performance.
Supports variable publishing rates, payload sizes, and burst patterns.
"""

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from std_msgs.msg import String, ByteMultiArray
from geometry_msgs.msg import Twist
import time
import random
import string
import threading
from typing import Optional, Dict, Any


class MessageStressPublisher(Node):
    """ROS 2 node for publishing configurable stress test messages."""
    
    def __init__(self):
        super().__init__('message_stress_publisher')
        
        # Declare parameters with defaults
        self.declare_parameter('publish_rate', 10.0)
        self.declare_parameter('payload_size', 1024)
        self.declare_parameter('topic_name', 'stress_test_topic')
        self.declare_parameter('message_type', 'string')
        self.declare_parameter('burst_mode', False)
        self.declare_parameter('burst_high_rate', 100.0)
        self.declare_parameter('burst_low_rate', 1.0)
        self.declare_parameter('burst_duration', 5.0)
        self.declare_parameter('qos_reliability', 'reliable')
        self.declare_parameter('qos_durability', 'volatile')
        self.declare_parameter('qos_history', 'keep_last')
        self.declare_parameter('qos_depth', 10)
        
        # Initialize state
        self.message_counter = 0
        self.start_time = time.time()
        self.last_publish_time = 0.0
        self.rate_statistics = {
            'actual_rates': [],
            'target_rate': 0.0,
            'min_rate': float('inf'),
            'max_rate': 0.0,
            'avg_rate': 0.0
        }
        
        # Burst mode state
        self.burst_state = 'low'  # 'low' or 'high'
        self.burst_start_time = time.time()
        
        # Thread safety
        self.publisher_lock = threading.Lock()
        self.stats_lock = threading.Lock()
        
        # Setup publisher and timer
        self._setup_publisher()
        self._setup_timer()
        
        # Parameter callback for runtime reconfiguration
        self.add_on_set_parameters_callback(self._parameter_callback)
        
        self.get_logger().info(f"MessageStressPublisher initialized")
        self.get_logger().info(f"  Topic: {self.get_parameter('topic_name').value}")
        self.get_logger().info(f"  Rate: {self.get_parameter('publish_rate').value} Hz")
        self.get_logger().info(f"  Payload: {self.get_parameter('payload_size').value} bytes")
        self.get_logger().info(f"  Type: {self.get_parameter('message_type').value}")
        
    def _setup_publisher(self):
        """Setup publisher with appropriate QoS settings."""
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
        
        # Create publisher based on message type
        topic_name = self.get_parameter('topic_name').value
        message_type = self.get_parameter('message_type').value
        
        if message_type == 'string':
            self.publisher = self.create_publisher(String, topic_name, qos_profile)
        elif message_type == 'bytes':
            self.publisher = self.create_publisher(ByteMultiArray, topic_name, qos_profile)
        elif message_type == 'twist':
            self.publisher = self.create_publisher(Twist, topic_name, qos_profile)
        else:
            self.get_logger().warn(f"Unknown message type: {message_type}, using string")
            self.publisher = self.create_publisher(String, topic_name, qos_profile)
            
    def _setup_timer(self):
        """Setup publishing timer based on current rate."""
        publish_rate = self.get_parameter('publish_rate').value
        
        if hasattr(self, 'timer'):
            self.timer.cancel()
            
        if publish_rate > 0:
            timer_period = 1.0 / publish_rate
            self.timer = self.create_timer(timer_period, self._timer_callback)
            
            with self.stats_lock:
                self.rate_statistics['target_rate'] = publish_rate
        else:
            self.get_logger().warn("Invalid publish rate, timer not started")
            
    def _timer_callback(self):
        """Timer callback for publishing messages."""
        current_time = time.time()
        
        # Handle burst mode
        if self.get_parameter('burst_mode').value:
            self._handle_burst_mode(current_time)
        
        # Generate and publish message
        message = self._generate_message()
        
        with self.publisher_lock:
            try:
                self.publisher.publish(message)
                self.message_counter += 1
                
                # Update rate statistics
                if self.last_publish_time > 0:
                    actual_rate = 1.0 / (current_time - self.last_publish_time)
                    self._update_rate_statistics(actual_rate)
                
                self.last_publish_time = current_time
                
            except Exception as e:
                self.get_logger().error(f"Publishing failed: {e}")
                
    def _handle_burst_mode(self, current_time: float):
        """Handle burst mode rate switching."""
        burst_duration = self.get_parameter('burst_duration').value
        time_in_state = current_time - self.burst_start_time
        
        if time_in_state >= burst_duration:
            # Switch burst state
            if self.burst_state == 'low':
                self.burst_state = 'high'
                new_rate = self.get_parameter('burst_high_rate').value
            else:
                self.burst_state = 'low'
                new_rate = self.get_parameter('burst_low_rate').value
                
            self.get_logger().info(f"Burst mode: switching to {self.burst_state} rate ({new_rate} Hz)")
            
            # Update timer with new rate
            self.set_parameters([Parameter('publish_rate', Parameter.Type.DOUBLE, new_rate)])
            self.burst_start_time = current_time
            
    def _generate_message(self):
        """Generate message based on configured type and payload size."""
        message_type = self.get_parameter('message_type').value
        payload_size = self.get_parameter('payload_size').value
        
        # Add timestamp for latency measurement
        timestamp = time.time_ns()
        
        if message_type == 'string':
            # Generate string payload
            if payload_size <= 50:  # Small messages with timestamp
                content = f"msg_{self.message_counter}_ts_{timestamp}"
            else:
                # Large messages with random content
                random_data = ''.join(random.choices(string.ascii_letters + string.digits, 
                                                   k=max(1, payload_size - 50)))
                content = f"msg_{self.message_counter}_ts_{timestamp}_{random_data}"
            
            message = String()
            message.data = content[:payload_size]  # Ensure exact size
            
        elif message_type == 'bytes':
            # Generate byte array payload
            message = ByteMultiArray()
            # Include timestamp in first 8 bytes
            timestamp_bytes = timestamp.to_bytes(8, byteorder='little')
            random_bytes = bytes(random.randint(0, 255) for _ in range(max(0, payload_size - 8)))
            message.data = list(timestamp_bytes + random_bytes)
            
        elif message_type == 'twist':
            # Generate Twist message (fixed size, embed timestamp in unused field)
            message = Twist()
            message.linear.x = float(self.message_counter % 100) / 10.0
            message.linear.y = random.uniform(-1.0, 1.0)
            message.linear.z = random.uniform(-1.0, 1.0)
            message.angular.x = random.uniform(-1.0, 1.0)
            message.angular.y = random.uniform(-1.0, 1.0)
            # Embed timestamp in angular.z (for latency measurement)
            message.angular.z = float(timestamp % 1000000) / 1000000.0
            
        else:
            # Fallback to string
            message = String()
            message.data = f"msg_{self.message_counter}_ts_{timestamp}"
            
        return message
        
    def _update_rate_statistics(self, actual_rate: float):
        """Update publishing rate statistics."""
        with self.stats_lock:
            self.rate_statistics['actual_rates'].append(actual_rate)
            
            # Keep only last 100 samples for rolling average
            if len(self.rate_statistics['actual_rates']) > 100:
                self.rate_statistics['actual_rates'].pop(0)
                
            # Update min/max/average
            self.rate_statistics['min_rate'] = min(self.rate_statistics['min_rate'], actual_rate)
            self.rate_statistics['max_rate'] = max(self.rate_statistics['max_rate'], actual_rate)
            
            if self.rate_statistics['actual_rates']:
                self.rate_statistics['avg_rate'] = sum(self.rate_statistics['actual_rates']) / len(self.rate_statistics['actual_rates'])
                
    def _parameter_callback(self, params):
        """Handle parameter updates for runtime reconfiguration."""
        for param in params:
            if param.name == 'publish_rate':
                self.get_logger().info(f"Updating publish rate to {param.value} Hz")
                self._setup_timer()
            elif param.name in ['topic_name', 'message_type', 'qos_reliability', 'qos_durability', 'qos_history', 'qos_depth']:
                self.get_logger().info(f"Updating publisher configuration: {param.name} = {param.value}")
                self._setup_publisher()
            elif param.name == 'burst_mode':
                if param.value:
                    self.get_logger().info("Enabling burst mode")
                    self.burst_start_time = time.time()
                    self.burst_state = 'low'
                else:
                    self.get_logger().info("Disabling burst mode")
                    
        return rclpy.parameter.SetParametersResult(successful=True)
        
    def get_statistics(self) -> Dict[str, Any]:
        """Get current publishing statistics."""
        current_time = time.time()
        runtime = current_time - self.start_time
        
        with self.stats_lock:
            stats = {
                'message_count': self.message_counter,
                'runtime_seconds': runtime,
                'average_rate': self.message_counter / runtime if runtime > 0 else 0.0,
                'target_rate': self.rate_statistics['target_rate'],
                'actual_rate_stats': {
                    'min': self.rate_statistics['min_rate'] if self.rate_statistics['min_rate'] != float('inf') else 0.0,
                    'max': self.rate_statistics['max_rate'],
                    'avg': self.rate_statistics['avg_rate']
                },
                'burst_mode': self.get_parameter('burst_mode').value,
                'burst_state': self.burst_state if self.get_parameter('burst_mode').value else None
            }
            
        return stats
        
    def log_statistics(self):
        """Log current statistics."""
        stats = self.get_statistics()
        self.get_logger().info(f"Statistics: {stats['message_count']} messages in {stats['runtime_seconds']:.1f}s")
        self.get_logger().info(f"  Average rate: {stats['average_rate']:.2f} Hz (target: {stats['target_rate']:.2f} Hz)")
        self.get_logger().info(f"  Actual rate - min: {stats['actual_rate_stats']['min']:.2f}, max: {stats['actual_rate_stats']['max']:.2f}, avg: {stats['actual_rate_stats']['avg']:.2f}")


def main(args=None):
    """Main entry point for message stress publisher."""
    rclpy.init(args=args)
    
    try:
        publisher_node = MessageStressPublisher()
        
        # Setup statistics logging timer
        def log_stats():
            publisher_node.log_statistics()
            
        stats_timer = publisher_node.create_timer(10.0, log_stats)  # Log every 10 seconds
        
        rclpy.spin(publisher_node)
        
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'publisher_node' in locals():
            publisher_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()