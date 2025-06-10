#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_msgs.msg import String, Float32, Bool
from sensor_msgs.msg import JointState
import json
import signal
import sys

from .cpu_stress import CPUStressTester
from .memory_stress import MemoryStressTester
from .system_monitor import SystemMonitor


class StressTestNode(Node):
    """ROS 2 node for system stress testing with monitoring and safety"""
    
    def __init__(self):
        super().__init__('stress_test_node')
        
        # Initialize stress testers and monitor
        self.cpu_tester = CPUStressTester()
        self.memory_tester = MemoryStressTester()
        self.system_monitor = SystemMonitor()
        
        # Declare parameters
        self.declare_parameters(
            namespace='',
            parameters=[
                ('cpu_intensity', 0.7),
                ('memory_target_mb', 512),
                ('auto_start', False),
                ('duration_seconds', 0),  # 0 = indefinite
                ('enable_safety_monitoring', True),
                ('publish_rate_hz', 1.0)
            ]
        )
        
        # Publishers
        self.status_publisher = self.create_publisher(String, 'stress_status', 10)
        self.metrics_publisher = self.create_publisher(String, 'system_metrics', 10)
        self.cpu_load_publisher = self.create_publisher(Float32, 'cpu_load', 10)
        self.memory_usage_publisher = self.create_publisher(Float32, 'memory_usage', 10)
        
        # Subscribers
        self.control_subscriber = self.create_subscription(
            String, 'stress_control', self.control_callback, 10)
        
        self.cpu_control_subscriber = self.create_subscription(
            Float32, 'cpu_intensity_control', self.cpu_intensity_callback, 10)
        
        self.memory_control_subscriber = self.create_subscription(
            Float32, 'memory_target_control', self.memory_target_callback, 10)
        
        # Timers
        publish_rate = self.get_parameter('publish_rate_hz').get_parameter_value().double_value
        self.publish_timer = self.create_timer(1.0 / publish_rate, self.publish_status)
        
        # Setup system monitoring with alert callback
        self.system_monitor.add_alert_callback(self.system_alert_callback)
        
        # Start monitoring if enabled
        if self.get_parameter('enable_safety_monitoring').get_parameter_value().bool_value:
            self.system_monitor.start_monitoring()
            self.get_logger().info('Safety monitoring enabled')
        
        # Auto-start if configured
        if self.get_parameter('auto_start').get_parameter_value().bool_value:
            self.start_stress_test()
        
        self.get_logger().info('Stress test node initialized')
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.get_logger().info('Received shutdown signal, stopping stress tests...')
        self.stop_stress_test()
        rclpy.shutdown()
    
    def control_callback(self, msg):
        """Handle control commands"""
        try:
            command = msg.data.lower().strip()
            
            if command == 'start':
                success = self.start_stress_test()
                self.get_logger().info(f'Start command: {"Success" if success else "Failed"}')
            elif command == 'stop':
                success = self.stop_stress_test()
                self.get_logger().info(f'Stop command: {"Success" if success else "Failed"}')
            elif command == 'restart':
                self.stop_stress_test()
                success = self.start_stress_test()
                self.get_logger().info(f'Restart command: {"Success" if success else "Failed"}')
            else:
                self.get_logger().warn(f'Unknown command: {command}')
                
        except Exception as e:
            self.get_logger().error(f'Control callback error: {e}')
    
    def cpu_intensity_callback(self, msg):
        """Handle CPU intensity adjustment"""
        try:
            intensity = max(0.0, min(1.0, msg.data))  # Clamp to 0-1
            self.cpu_tester.adjust_intensity(intensity)
            self.get_logger().info(f'CPU intensity adjusted to {intensity:.2f}')
        except Exception as e:
            self.get_logger().error(f'CPU intensity callback error: {e}')
    
    def memory_target_callback(self, msg):
        """Handle memory target adjustment"""
        try:
            target_mb = max(0, int(msg.data))
            if self.memory_tester.is_running:
                self.memory_tester.stop_stress_test()
                self.memory_tester.start_stress_test(target_mb)
                self.get_logger().info(f'Memory target adjusted to {target_mb} MB')
        except Exception as e:
            self.get_logger().error(f'Memory target callback error: {e}')
    
    def system_alert_callback(self, alert):
        """Handle system monitoring alerts"""
        self.get_logger().warn(f'System Alert: {alert["message"]}')
        
        # Auto-stop on critical alerts if safety monitoring is enabled
        if alert['type'].endswith('_critical'):
            self.get_logger().error('Critical system condition detected, stopping stress tests')
            self.stop_stress_test()
    
    def start_stress_test(self):
        """Start stress testing based on parameters"""
        try:
            # Get parameters
            cpu_intensity = self.get_parameter('cpu_intensity').get_parameter_value().double_value
            memory_target = int(self.get_parameter('memory_target_mb').get_parameter_value().integer_value)
            duration = self.get_parameter('duration_seconds').get_parameter_value().integer_value
            duration = None if duration <= 0 else duration
            
            # Check system safety before starting
            if not self.system_monitor.is_system_safe():
                self.get_logger().error('System not in safe condition, cannot start stress test')
                return False
            
            # Start CPU stress test
            cpu_success = self.cpu_tester.start_stress_test(cpu_intensity, duration)
            
            # Start memory stress test
            memory_success = self.memory_tester.start_stress_test(memory_target, duration)
            
            if cpu_success and memory_success:
                self.get_logger().info(f'Stress test started: CPU={cpu_intensity:.2f}, Memory={memory_target}MB')
                return True
            else:
                self.get_logger().error('Failed to start one or more stress tests')
                return False
                
        except Exception as e:
            self.get_logger().error(f'Start stress test error: {e}')
            return False
    
    def stop_stress_test(self):
        """Stop all stress testing"""
        try:
            cpu_stopped = self.cpu_tester.stop_stress_test()
            memory_stopped = self.memory_tester.stop_stress_test()
            
            if cpu_stopped or memory_stopped:
                self.get_logger().info('Stress tests stopped')
                return True
            return False
            
        except Exception as e:
            self.get_logger().error(f'Stop stress test error: {e}')
            return False
    
    def publish_status(self):
        """Publish current status and metrics"""
        try:
            # Get status from all components
            cpu_status = self.cpu_tester.get_status()
            memory_status = self.memory_tester.get_status()
            system_stats = self.system_monitor.get_current_stats()
            
            # Publish detailed status
            status_data = {
                'timestamp': self.get_clock().now().to_msg(),
                'cpu_stress': cpu_status,
                'memory_stress': memory_status,
                'system_stats': system_stats
            }
            
            status_msg = String()
            status_msg.data = json.dumps(status_data, default=str)
            self.status_publisher.publish(status_msg)
            
            # Publish individual metrics
            cpu_load_msg = Float32()
            cpu_load_msg.data = float(system_stats['cpu_percent'])
            self.cpu_load_publisher.publish(cpu_load_msg)
            
            memory_usage_msg = Float32()
            memory_usage_msg.data = float(system_stats['memory_percent'])
            self.memory_usage_publisher.publish(memory_usage_msg)
            
            # Publish system metrics
            metrics_msg = String()
            metrics_msg.data = json.dumps(system_stats, default=str)
            self.metrics_publisher.publish(metrics_msg)
            
        except Exception as e:
            self.get_logger().error(f'Publish status error: {e}')
    
    def destroy_node(self):
        """Clean shutdown"""
        self.get_logger().info('Shutting down stress test node...')
        self.stop_stress_test()
        self.system_monitor.stop_monitoring()
        super().destroy_node()


def main(args=None):
    """Main entry point"""
    rclpy.init(args=args)
    
    try:
        stress_node = StressTestNode()
        rclpy.spin(stress_node)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f'Node error: {e}')
    finally:
        if 'stress_node' in locals():
            stress_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()