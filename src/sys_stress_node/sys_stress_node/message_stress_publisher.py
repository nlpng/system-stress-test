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
from std_msgs.msg import String, ByteMultiArray, Header
from geometry_msgs.msg import Twist
from sensor_msgs.msg import Image, PointCloud2, LaserScan, PointField
import time
import random
import string
import threading
import numpy as np
from typing import Optional, Dict, Any, Union
import struct


class MessageStressPublisher(Node):
    """ROS 2 node for publishing configurable stress test messages."""
    
    def __init__(self):
        super().__init__('message_stress_publisher')
        
        # Declare parameters with defaults
        self.declare_parameter('publish_rate', 10.0)
        self.declare_parameter('payload_size', 1024)
        self.declare_parameter('topic_name', 'stress_test_topic')
        self.declare_parameter('message_type', 'string')
        self.declare_parameter('image_width', 640)
        self.declare_parameter('image_height', 480)
        self.declare_parameter('image_encoding', 'rgb8')
        self.declare_parameter('pointcloud_points', 10000)
        self.declare_parameter('laserscan_ranges', 360)
        self.declare_parameter('custom_payload_fields', 100)
        self.declare_parameter('dynamic_type_switching', False)
        self.declare_parameter('type_switch_interval', 10.0)
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
        
        # Dynamic message type switching
        self.available_types = ['string', 'bytes', 'twist', 'image', 'pointcloud2', 'laserscan', 'custom_large']
        self.current_type_index = 0
        self.last_type_switch = time.time()
        
        # Pre-generated data for efficiency
        self.cached_image_data = None
        self.cached_pointcloud_data = None
        
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
        
        # Create publishers for all supported message types
        self.publishers = {}
        
        # Basic message types
        self.publishers['string'] = self.create_publisher(String, f"{topic_name}_string", qos_profile)
        self.publishers['bytes'] = self.create_publisher(ByteMultiArray, f"{topic_name}_bytes", qos_profile)
        self.publishers['twist'] = self.create_publisher(Twist, f"{topic_name}_twist", qos_profile)
        
        # Sensor message types
        self.publishers['image'] = self.create_publisher(Image, f"{topic_name}_image", qos_profile)
        self.publishers['pointcloud2'] = self.create_publisher(PointCloud2, f"{topic_name}_pointcloud2", qos_profile)
        self.publishers['laserscan'] = self.create_publisher(LaserScan, f"{topic_name}_laserscan", qos_profile)
        
        # Custom large payload (using ByteMultiArray with structured data)
        self.publishers['custom_large'] = self.create_publisher(ByteMultiArray, f"{topic_name}_custom_large", qos_profile)
        
        # Set current publisher based on message type
        if message_type in self.publishers:
            self.publisher = self.publishers[message_type]
        else:
            self.get_logger().warn(f"Unknown message type: {message_type}, using string")
            self.publisher = self.publishers['string']
            
        # Pre-generate complex data structures for efficiency
        self._generate_cached_data()
            
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
            
        # Handle dynamic message type switching
        if self.get_parameter('dynamic_type_switching').value:
            self._handle_type_switching(current_time)
        
        # Generate and publish message
        message = self._generate_message()
        
        with self.publisher_lock:
            try:
                # Publish to appropriate publisher based on message type
                current_type = self.get_parameter('message_type').value
                if self.get_parameter('dynamic_type_switching').value:
                    current_type = self.available_types[self.current_type_index]
                    
                if current_type in self.publishers:
                    self.publishers[current_type].publish(message)
                else:
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
            
    def _handle_type_switching(self, current_time: float):
        """Handle dynamic message type switching."""
        switch_interval = self.get_parameter('type_switch_interval').value
        time_since_switch = current_time - self.last_type_switch
        
        if time_since_switch >= switch_interval:
            # Switch to next message type
            self.current_type_index = (self.current_type_index + 1) % len(self.available_types)
            new_type = self.available_types[self.current_type_index]
            
            self.get_logger().info(f"Dynamic type switch: switching to {new_type}")
            self.last_type_switch = current_time
            
    def _generate_cached_data(self):
        """Pre-generate complex data structures for performance."""
        # Pre-generate image data
        width = self.get_parameter('image_width').value
        height = self.get_parameter('image_height').value
        encoding = self.get_parameter('image_encoding').value
        
        if encoding == 'rgb8':
            channels = 3
        elif encoding == 'rgba8':
            channels = 4
        elif encoding == 'mono8':
            channels = 1
        else:
            channels = 3
            
        # Generate random image data
        self.cached_image_data = np.random.randint(0, 256, (height, width, channels), dtype=np.uint8)
        
        # Pre-generate point cloud data
        num_points = self.get_parameter('pointcloud_points').value
        # Generate random 3D points with RGB values
        self.cached_pointcloud_data = np.random.randn(num_points, 6).astype(np.float32)  # x,y,z,r,g,b
        
    def _generate_string_message(self, payload_size: int, timestamp: int) -> String:
        """Generate string message with embedded timestamp."""
        if payload_size <= 50:
            content = f"msg_{self.message_counter}_ts_{timestamp}"
        else:
            random_data = ''.join(random.choices(string.ascii_letters + string.digits, 
                                               k=max(1, payload_size - 50)))
            content = f"msg_{self.message_counter}_ts_{timestamp}_{random_data}"
        
        message = String()
        message.data = content[:payload_size]
        return message
        
    def _generate_bytes_message(self, payload_size: int, timestamp: int) -> ByteMultiArray:
        """Generate byte array message with embedded timestamp."""
        message = ByteMultiArray()
        timestamp_bytes = timestamp.to_bytes(8, byteorder='little')
        random_bytes = bytes(random.randint(0, 255) for _ in range(max(0, payload_size - 8)))
        message.data = list(timestamp_bytes + random_bytes)
        return message
        
    def _generate_twist_message(self, timestamp: int) -> Twist:
        """Generate Twist message with embedded timestamp."""
        message = Twist()
        message.linear.x = float(self.message_counter % 100) / 10.0
        message.linear.y = random.uniform(-1.0, 1.0)
        message.linear.z = random.uniform(-1.0, 1.0)
        message.angular.x = random.uniform(-1.0, 1.0)
        message.angular.y = random.uniform(-1.0, 1.0)
        message.angular.z = float(timestamp % 1000000) / 1000000.0
        return message
        
    def _generate_image_message(self, timestamp: int) -> Image:
        """Generate realistic Image message."""
        message = Image()
        
        # Create header with timestamp
        message.header = Header()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "camera_frame"
        
        # Image properties
        message.width = self.get_parameter('image_width').value
        message.height = self.get_parameter('image_height').value
        message.encoding = self.get_parameter('image_encoding').value
        
        if message.encoding == 'rgb8':
            message.step = message.width * 3
        elif message.encoding == 'rgba8':
            message.step = message.width * 4
        elif message.encoding == 'mono8':
            message.step = message.width
        else:
            message.step = message.width * 3
            
        message.is_bigendian = False
        
        # Add some variation to the cached image data for realism
        if self.cached_image_data is not None:
            # Add timestamp as noise pattern
            noise_factor = (timestamp % 1000) / 1000.0
            varied_data = (self.cached_image_data.astype(float) * (0.9 + 0.2 * noise_factor)).astype(np.uint8)
            message.data = varied_data.flatten().tolist()
        else:
            # Fallback: generate random data
            data_size = message.height * message.step
            message.data = [random.randint(0, 255) for _ in range(data_size)]
            
        return message
        
    def _generate_pointcloud2_message(self, timestamp: int) -> PointCloud2:
        """Generate realistic PointCloud2 message."""
        message = PointCloud2()
        
        # Create header
        message.header = Header()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "lidar_frame"
        
        # Define point fields (x, y, z, rgb)
        message.fields = [
            PointField(name='x', offset=0, datatype=PointField.FLOAT32, count=1),
            PointField(name='y', offset=4, datatype=PointField.FLOAT32, count=1),
            PointField(name='z', offset=8, datatype=PointField.FLOAT32, count=1),
            PointField(name='rgb', offset=12, datatype=PointField.FLOAT32, count=1),
        ]
        
        # Point cloud properties
        num_points = self.get_parameter('pointcloud_points').value
        message.height = 1  # Unorganized point cloud
        message.width = num_points
        message.point_step = 16  # 4 fields * 4 bytes each
        message.row_step = message.point_step * message.width
        message.is_dense = True
        
        # Generate or use cached point data
        if self.cached_pointcloud_data is not None and len(self.cached_pointcloud_data) >= num_points:
            # Add timestamp-based variation
            variation = (timestamp % 10000) / 10000.0
            points = self.cached_pointcloud_data[:num_points].copy()
            points[:, :3] += variation * 0.1  # Add small positional noise
            
            # Pack point data into bytes
            data_bytes = bytearray()
            for point in points:
                # Pack x, y, z as floats
                data_bytes.extend(struct.pack('fff', float(point[0]), float(point[1]), float(point[2])))
                # Pack RGB as a single float (simplified)
                rgb_value = (int(point[3] * 255) << 16) | (int(point[4] * 255) << 8) | int(point[5] * 255)
                data_bytes.extend(struct.pack('f', float(rgb_value)))
                
            message.data = list(data_bytes)
        else:
            # Fallback: generate random point cloud data
            data_bytes = bytearray()
            for _ in range(num_points):
                # Random 3D point
                x, y, z = random.uniform(-10, 10), random.uniform(-10, 10), random.uniform(0, 5)
                data_bytes.extend(struct.pack('fff', x, y, z))
                # Random RGB
                rgb = random.randint(0, 0xFFFFFF)
                data_bytes.extend(struct.pack('f', float(rgb)))
            message.data = list(data_bytes)
            
        return message
        
    def _generate_laserscan_message(self, timestamp: int) -> LaserScan:
        """Generate realistic LaserScan message."""
        message = LaserScan()
        
        # Create header
        message.header = Header()
        message.header.stamp = self.get_clock().now().to_msg()
        message.header.frame_id = "laser_frame"
        
        # Laser scan properties
        num_ranges = self.get_parameter('laserscan_ranges').value
        message.angle_min = -3.14159  # -180 degrees
        message.angle_max = 3.14159   # +180 degrees
        message.angle_increment = (message.angle_max - message.angle_min) / num_ranges
        message.time_increment = 0.0001  # Time between measurements
        message.scan_time = 0.1  # Time for complete scan
        message.range_min = 0.1
        message.range_max = 30.0
        
        # Generate realistic range data (simulate environment)
        ranges = []
        intensities = []
        
        for i in range(num_ranges):
            angle = message.angle_min + i * message.angle_increment
            
            # Simulate some obstacles and walls
            base_range = 5.0 + 3.0 * abs(np.sin(angle * 2))  # Basic pattern
            
            # Add timestamp-based variation for dynamic environment
            time_variation = 0.5 * np.sin(timestamp / 1000000000.0 + angle)
            range_value = base_range + time_variation
            
            # Add some noise
            range_value += random.uniform(-0.1, 0.1)
            
            # Clamp to valid range
            range_value = max(message.range_min, min(message.range_max, range_value))
            ranges.append(range_value)
            
            # Generate intensity based on range (closer = higher intensity)
            intensity = max(0.0, 1000.0 / (range_value + 1.0))
            intensities.append(intensity)
            
        message.ranges = ranges
        message.intensities = intensities
        
        return message
        
    def _generate_custom_large_message(self, payload_size: int, timestamp: int) -> ByteMultiArray:
        """Generate custom large payload message with structured data."""
        message = ByteMultiArray()
        
        # Create structured large payload
        num_fields = self.get_parameter('custom_payload_fields').value
        
        # Start with timestamp and metadata
        data_bytes = bytearray()
        data_bytes.extend(timestamp.to_bytes(8, byteorder='little'))  # Timestamp
        data_bytes.extend(self.message_counter.to_bytes(4, byteorder='little'))  # Message ID
        data_bytes.extend(num_fields.to_bytes(4, byteorder='little'))  # Number of fields
        
        # Add structured field data
        bytes_per_field = max(1, (payload_size - 16) // num_fields)  # Reserve 16 bytes for header
        
        for field_id in range(num_fields):
            # Field header: field_id (4 bytes) + field_size (4 bytes)
            data_bytes.extend(field_id.to_bytes(4, byteorder='little'))
            data_bytes.extend(bytes_per_field.to_bytes(4, byteorder='little'))
            
            # Field data: mix of patterns and random data
            for byte_idx in range(max(1, bytes_per_field - 8)):
                if byte_idx % 4 == 0:
                    # Structured pattern based on timestamp and field
                    pattern_value = (timestamp + field_id + byte_idx) % 256
                    data_bytes.append(pattern_value)
                else:
                    # Random data
                    data_bytes.append(random.randint(0, 255))
                    
        # Pad or truncate to exact payload size
        if len(data_bytes) < payload_size:
            data_bytes.extend(bytes(random.randint(0, 255) for _ in range(payload_size - len(data_bytes))))
        elif len(data_bytes) > payload_size:
            data_bytes = data_bytes[:payload_size]
            
        message.data = list(data_bytes)
        return message
            
    def _generate_message(self) -> Union[String, ByteMultiArray, Twist, Image, PointCloud2, LaserScan]:
        """Generate message based on configured type and payload size."""
        message_type = self.get_parameter('message_type').value
        
        # Use current type if dynamic switching is enabled
        if self.get_parameter('dynamic_type_switching').value:
            message_type = self.available_types[self.current_type_index]
            
        payload_size = self.get_parameter('payload_size').value
        timestamp = time.time_ns()
        
        if message_type == 'string':
            return self._generate_string_message(payload_size, timestamp)
        elif message_type == 'bytes':
            return self._generate_bytes_message(payload_size, timestamp)
        elif message_type == 'twist':
            return self._generate_twist_message(timestamp)
        elif message_type == 'image':
            return self._generate_image_message(timestamp)
        elif message_type == 'pointcloud2':
            return self._generate_pointcloud2_message(timestamp)
        elif message_type == 'laserscan':
            return self._generate_laserscan_message(timestamp)
        elif message_type == 'custom_large':
            return self._generate_custom_large_message(payload_size, timestamp)
        else:
            # Fallback to string
            return self._generate_string_message(payload_size, timestamp)
        
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
                'burst_state': self.burst_state if self.get_parameter('burst_mode').value else None,
                'message_type': self.get_parameter('message_type').value,
                'current_type': self.available_types[self.current_type_index] if self.get_parameter('dynamic_type_switching').value else self.get_parameter('message_type').value,
                'dynamic_switching': self.get_parameter('dynamic_type_switching').value
            }
            
        return stats
        
    def log_statistics(self):
        """Log current statistics."""
        stats = self.get_statistics()
        current_type = self.get_parameter('message_type').value
        if self.get_parameter('dynamic_type_switching').value:
            current_type = self.available_types[self.current_type_index]
            
        self.get_logger().info(f"Statistics: {stats['message_count']} messages in {stats['runtime_seconds']:.1f}s")
        self.get_logger().info(f"  Message type: {current_type}")
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