#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
import threading
import time
import statistics
from typing import Dict, List, Tuple, Optional
from std_msgs.msg import String, Int32, Float64
from sensor_msgs.msg import PointCloud2
import json
import signal
import sys

class ThroughputTester(Node):
    """
    ROS 2 node for testing message throughput limits and behavior under various conditions.
    Tests progressive frequency rates, queue overflow behavior, and system limits.
    """
    
    def __init__(self):
        super().__init__('throughput_tester')
        
        # Test configuration parameters
        self.declare_parameter('test_frequencies', [1, 10, 100, 1000, 10000])  # Hz
        self.declare_parameter('test_duration', 10.0)  # seconds per frequency test
        self.declare_parameter('max_queue_size', 10)
        self.declare_parameter('message_payload_size', 1024)  # bytes
        self.declare_parameter('enable_burst_testing', True)
        self.declare_parameter('burst_cycle_duration', 5.0)  # seconds
        self.declare_parameter('cpu_load_levels', [0, 25, 50, 75, 90])  # percentage
        
        # Test state tracking
        self.current_test_active = False
        self.test_results = {}
        self.message_counters = {}
        self.latency_measurements = {}
        self.queue_overflow_events = {}
        self.test_lock = threading.Lock()
        
        # Publishers and subscribers for throughput testing
        self.test_publishers = {}
        self.test_subscribers = {}
        self.subscriber_callbacks = {}
        
        # QoS profiles for different testing scenarios
        self.qos_reliable = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=self.get_parameter('max_queue_size').value
        )
        
        self.qos_best_effort = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=self.get_parameter('max_queue_size').value
        )
        
        # Results publisher
        self.results_publisher = self.create_publisher(
            String, 
            'throughput_test_results', 
            10
        )
        
        # Control subscriber for external test commands
        self.control_subscriber = self.create_subscription(
            String,
            'throughput_test_control',
            self.control_callback,
            10
        )
        
        # Baseline performance measurement
        self.baseline_metrics = None
        
        self.get_logger().info('ThroughputTester node initialized')
        
    def control_callback(self, msg):
        """Handle external control commands"""
        try:
            command_data = json.loads(msg.data)
            command = command_data.get('command', '')
            
            if command == 'start_frequency_test':
                frequencies = command_data.get('frequencies', self.get_parameter('test_frequencies').value)
                self.start_frequency_progression_test(frequencies)
            elif command == 'start_burst_test':
                self.start_burst_pattern_test()
            elif command == 'start_cpu_load_test':
                cpu_levels = command_data.get('cpu_levels', self.get_parameter('cpu_load_levels').value)
                self.start_cpu_load_throughput_test(cpu_levels)
            elif command == 'start_sustainable_rate_test':
                self.start_sustainable_rate_test()
            elif command == 'start_queue_overflow_test':
                self.start_queue_overflow_test()
            elif command == 'start_discovery_overhead_test':
                self.start_discovery_overhead_test()
            elif command == 'get_results':
                self.publish_current_results()
            elif command == 'stop_test':
                self.stop_current_test()
                
        except json.JSONDecodeError:
            self.get_logger().error(f'Invalid JSON in control message: {msg.data}')
        except Exception as e:
            self.get_logger().error(f'Error processing control command: {e}')
    
    def create_test_topic_pair(self, topic_name: str, message_type=String, qos_profile=None):
        """Create publisher-subscriber pair for testing"""
        if qos_profile is None:
            qos_profile = self.qos_reliable
            
        # Create publisher
        publisher = self.create_publisher(message_type, f'test_{topic_name}', qos_profile)
        
        # Create subscriber with callback tracking
        def create_callback(topic):
            def callback(msg):
                self.handle_test_message_received(topic, msg)
            return callback
        
        callback = create_callback(topic_name)
        subscriber = self.create_subscription(
            message_type,
            f'test_{topic_name}',
            callback,
            qos_profile
        )
        
        self.test_publishers[topic_name] = publisher
        self.test_subscribers[topic_name] = subscriber
        self.subscriber_callbacks[topic_name] = callback
        
        # Initialize tracking
        self.message_counters[topic_name] = {'sent': 0, 'received': 0, 'lost': 0}
        self.latency_measurements[topic_name] = []
        self.queue_overflow_events[topic_name] = 0
        
        return publisher, subscriber
    
    def handle_test_message_received(self, topic_name: str, msg):
        """Handle received test messages and calculate metrics"""
        with self.test_lock:
            self.message_counters[topic_name]['received'] += 1
            
            # Calculate latency if timestamp is embedded in message
            try:
                if hasattr(msg, 'data') and isinstance(msg.data, str):
                    msg_data = json.loads(msg.data)
                    if 'timestamp' in msg_data:
                        latency = time.time() - msg_data['timestamp']
                        self.latency_measurements[topic_name].append(latency)
            except (json.JSONDecodeError, AttributeError):
                pass  # Message doesn't contain timestamp data
    
    def start_frequency_progression_test(self, frequencies: List[int]):
        """Test progressive frequency rates: 1Hz → 10Hz → 100Hz → 1kHz → 10kHz"""
        if self.current_test_active:
            self.get_logger().warn('Test already active, skipping frequency progression test')
            return
            
        self.current_test_active = True
        self.get_logger().info(f'Starting frequency progression test: {frequencies} Hz')
        
        # Create test topic
        topic_name = 'frequency_progression'
        publisher, subscriber = self.create_test_topic_pair(topic_name)
        
        test_results = {}
        
        for frequency in frequencies:
            self.get_logger().info(f'Testing frequency: {frequency} Hz')
            
            # Reset counters
            with self.test_lock:
                self.message_counters[topic_name] = {'sent': 0, 'received': 0, 'lost': 0}
                self.latency_measurements[topic_name] = []
            
            # Calculate timer period
            if frequency > 0:
                timer_period = 1.0 / frequency
            else:
                timer_period = 1.0  # Fallback
            
            # Create timer for this frequency
            message_timer = self.create_timer(
                timer_period,
                lambda: self.publish_test_message(topic_name, publisher)
            )
            
            # Run test for specified duration
            test_duration = self.get_parameter('test_duration').value
            time.sleep(test_duration)
            
            # Stop timer
            message_timer.destroy()
            
            # Collect results
            with self.test_lock:
                sent = self.message_counters[topic_name]['sent']
                received = self.message_counters[topic_name]['received']
                lost = sent - received
                
                latencies = self.latency_measurements[topic_name].copy()
                
                test_results[frequency] = {
                    'target_frequency': frequency,
                    'actual_send_rate': sent / test_duration,
                    'actual_receive_rate': received / test_duration,
                    'messages_sent': sent,
                    'messages_received': received,
                    'messages_lost': lost,
                    'loss_rate': (lost / sent) if sent > 0 else 0.0,
                    'avg_latency': statistics.mean(latencies) if latencies else 0.0,
                    'max_latency': max(latencies) if latencies else 0.0,
                    'min_latency': min(latencies) if latencies else 0.0,
                    'latency_std': statistics.stdev(latencies) if len(latencies) > 1 else 0.0
                }
            
            self.get_logger().info(f'Frequency {frequency} Hz completed: '
                                 f'{received}/{sent} messages received '
                                 f'({(received/sent)*100:.1f}% success rate)')
        
        # Store results
        self.test_results['frequency_progression'] = test_results
        self.current_test_active = False
        
        # Publish results
        self.publish_test_results('frequency_progression', test_results)
        
        self.get_logger().info('Frequency progression test completed')
    
    def start_sustainable_rate_test(self):
        """Determine maximum sustainable message rate per topic"""
        if self.current_test_active:
            self.get_logger().warn('Test already active, skipping sustainable rate test')
            return
            
        self.current_test_active = True
        self.get_logger().info('Starting sustainable rate test')
        
        topic_name = 'sustainable_rate'
        publisher, subscriber = self.create_test_topic_pair(topic_name)
        
        # Binary search for maximum sustainable rate
        min_rate = 1
        max_rate = 20000  # Start with high upper bound
        sustainable_rate = 0
        tolerance = 0.05  # 5% message loss tolerance
        
        while max_rate - min_rate > 10:
            test_rate = (min_rate + max_rate) // 2
            self.get_logger().info(f'Testing rate: {test_rate} Hz')
            
            # Reset counters
            with self.test_lock:
                self.message_counters[topic_name] = {'sent': 0, 'received': 0, 'lost': 0}
            
            # Test this rate
            timer_period = 1.0 / test_rate
            message_timer = self.create_timer(
                timer_period,
                lambda: self.publish_test_message(topic_name, publisher)
            )
            
            time.sleep(5.0)  # Shorter test duration for binary search
            message_timer.destroy()
            
            # Check success rate
            with self.test_lock:
                sent = self.message_counters[topic_name]['sent']
                received = self.message_counters[topic_name]['received']
                loss_rate = (sent - received) / sent if sent > 0 else 1.0
            
            if loss_rate <= tolerance:
                sustainable_rate = test_rate
                min_rate = test_rate
                self.get_logger().info(f'Rate {test_rate} Hz sustainable (loss: {loss_rate:.3f})')
            else:
                max_rate = test_rate
                self.get_logger().info(f'Rate {test_rate} Hz not sustainable (loss: {loss_rate:.3f})')
        
        # Store results
        self.test_results['sustainable_rate'] = {
            'max_sustainable_rate': sustainable_rate,
            'loss_tolerance': tolerance,
            'search_range': {'min': 1, 'max': 20000}
        }
        
        self.current_test_active = False
        self.publish_test_results('sustainable_rate', self.test_results['sustainable_rate'])
        
        self.get_logger().info(f'Sustainable rate test completed: {sustainable_rate} Hz')
    
    def start_queue_overflow_test(self):
        """Test subscriber queue overflow behavior and recovery"""
        if self.current_test_active:
            self.get_logger().warn('Test already active, skipping queue overflow test')
            return
            
        self.current_test_active = True
        self.get_logger().info('Starting queue overflow test')
        
        topic_name = 'queue_overflow'
        
        # Use small queue size to force overflow
        small_queue_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=5  # Small queue to force overflow
        )
        
        publisher, subscriber = self.create_test_topic_pair(topic_name, qos_profile=small_queue_qos)
        
        # Publish at high rate to cause overflow
        overflow_rate = 1000  # Hz
        timer_period = 1.0 / overflow_rate
        
        # Reset counters
        with self.test_lock:
            self.message_counters[topic_name] = {'sent': 0, 'received': 0, 'lost': 0}
        
        # Start high-rate publishing
        message_timer = self.create_timer(
            timer_period,
            lambda: self.publish_test_message(topic_name, publisher)
        )
        
        # Monitor for overflow behavior
        test_duration = 10.0
        start_time = time.time()
        
        while time.time() - start_time < test_duration:
            time.sleep(0.1)
            
            with self.test_lock:
                sent = self.message_counters[topic_name]['sent']
                received = self.message_counters[topic_name]['received']
                
                if sent > 0:
                    current_loss_rate = (sent - received) / sent
                    if current_loss_rate > 0.1:  # 10% loss indicates overflow
                        self.queue_overflow_events[topic_name] += 1
        
        message_timer.destroy()
        
        # Test recovery - reduce rate and see if system recovers
        recovery_rate = 10  # Much lower rate
        recovery_timer_period = 1.0 / recovery_rate
        
        # Reset received counter to measure recovery
        recovery_start_received = self.message_counters[topic_name]['received']
        
        recovery_timer = self.create_timer(
            recovery_timer_period,
            lambda: self.publish_test_message(topic_name, publisher)
        )
        
        time.sleep(5.0)  # Recovery test duration
        recovery_timer.destroy()
        
        # Calculate recovery metrics
        with self.test_lock:
            total_sent = self.message_counters[topic_name]['sent']
            total_received = self.message_counters[topic_name]['received']
            recovery_received = total_received - recovery_start_received
            
            overflow_results = {
                'overflow_rate_hz': overflow_rate,
                'recovery_rate_hz': recovery_rate,
                'total_sent': total_sent,
                'total_received': total_received,
                'total_loss_rate': (total_sent - total_received) / total_sent if total_sent > 0 else 0,
                'overflow_events_detected': self.queue_overflow_events[topic_name],
                'recovery_messages_received': recovery_received,
                'queue_size': small_queue_qos.depth
            }
        
        self.test_results['queue_overflow'] = overflow_results
        self.current_test_active = False
        
        self.publish_test_results('queue_overflow', overflow_results)
        self.get_logger().info('Queue overflow test completed')
    
    def start_burst_pattern_test(self):
        """Test message rate burst patterns (1Hz → 1kHz → 1Hz cycles)"""
        if self.current_test_active:
            self.get_logger().warn('Test already active, skipping burst pattern test')
            return
            
        self.current_test_active = True
        self.get_logger().info('Starting burst pattern test')
        
        topic_name = 'burst_pattern'
        publisher, subscriber = self.create_test_topic_pair(topic_name)
        
        # Burst pattern configuration
        low_rate = 1    # Hz
        high_rate = 1000  # Hz
        cycle_duration = self.get_parameter('burst_cycle_duration').value
        num_cycles = 3
        
        burst_results = []
        
        for cycle in range(num_cycles):
            self.get_logger().info(f'Starting burst cycle {cycle + 1}/{num_cycles}')
            
            # Low rate phase
            with self.test_lock:
                self.message_counters[topic_name] = {'sent': 0, 'received': 0, 'lost': 0}
            
            low_timer = self.create_timer(
                1.0 / low_rate,
                lambda: self.publish_test_message(topic_name, publisher)
            )
            
            time.sleep(cycle_duration)
            low_timer.destroy()
            
            low_phase_sent = self.message_counters[topic_name]['sent']
            low_phase_received = self.message_counters[topic_name]['received']
            
            # High rate phase
            high_timer = self.create_timer(
                1.0 / high_rate,
                lambda: self.publish_test_message(topic_name, publisher)
            )
            
            time.sleep(cycle_duration)
            high_timer.destroy()
            
            with self.test_lock:
                total_sent = self.message_counters[topic_name]['sent']
                total_received = self.message_counters[topic_name]['received']
                
                high_phase_sent = total_sent - low_phase_sent
                high_phase_received = total_received - low_phase_received
                
                cycle_results = {
                    'cycle': cycle + 1,
                    'low_rate_hz': low_rate,
                    'high_rate_hz': high_rate,
                    'low_phase': {
                        'sent': low_phase_sent,
                        'received': low_phase_received,
                        'loss_rate': (low_phase_sent - low_phase_received) / low_phase_sent if low_phase_sent > 0 else 0
                    },
                    'high_phase': {
                        'sent': high_phase_sent,
                        'received': high_phase_received,
                        'loss_rate': (high_phase_sent - high_phase_received) / high_phase_sent if high_phase_sent > 0 else 0
                    }
                }
                
                burst_results.append(cycle_results)
        
        self.test_results['burst_pattern'] = burst_results
        self.current_test_active = False
        
        self.publish_test_results('burst_pattern', burst_results)
        self.get_logger().info('Burst pattern test completed')
    
    def start_cpu_load_throughput_test(self, cpu_levels: List[int]):
        """Test throughput degradation under CPU load"""
        if self.current_test_active:
            self.get_logger().warn('Test already active, skipping CPU load throughput test')
            return
            
        self.current_test_active = True
        self.get_logger().info(f'Starting CPU load throughput test: {cpu_levels}%')
        
        # This test requires coordination with the CPU stress module
        # Send commands to CPU stress module and measure throughput
        
        topic_name = 'cpu_load_throughput'
        publisher, subscriber = self.create_test_topic_pair(topic_name)
        
        test_frequency = 100  # Hz - moderate frequency for testing
        timer_period = 1.0 / test_frequency
        test_duration = 10.0
        
        cpu_load_results = {}
        
        for cpu_level in cpu_levels:
            self.get_logger().info(f'Testing throughput under {cpu_level}% CPU load')
            
            # Send CPU stress command (this would integrate with existing CPU stress module)
            cpu_command = {
                'command': 'set_cpu_load',
                'cpu_percentage': cpu_level,
                'duration': test_duration + 2  # Extra time for measurement
            }
            
            # Reset counters
            with self.test_lock:
                self.message_counters[topic_name] = {'sent': 0, 'received': 0, 'lost': 0}
                self.latency_measurements[topic_name] = []
            
            # TODO: Send CPU stress command to cpu_stress module
            # This would be done through a separate publisher to cpu_stress_control topic
            
            # Start message publishing
            message_timer = self.create_timer(
                timer_period,
                lambda: self.publish_test_message(topic_name, publisher)
            )
            
            time.sleep(test_duration)
            message_timer.destroy()
            
            # Collect results
            with self.test_lock:
                sent = self.message_counters[topic_name]['sent']
                received = self.message_counters[topic_name]['received']
                latencies = self.latency_measurements[topic_name].copy()
                
                cpu_load_results[cpu_level] = {
                    'cpu_load_percent': cpu_level,
                    'target_frequency': test_frequency,
                    'messages_sent': sent,
                    'messages_received': received,
                    'actual_throughput': received / test_duration,
                    'loss_rate': (sent - received) / sent if sent > 0 else 0,
                    'avg_latency': statistics.mean(latencies) if latencies else 0.0,
                    'max_latency': max(latencies) if latencies else 0.0
                }
            
            # Stop CPU stress
            # TODO: Send stop command to cpu_stress module
            
            time.sleep(2)  # Cool down period
        
        self.test_results['cpu_load_throughput'] = cpu_load_results
        self.current_test_active = False
        
        self.publish_test_results('cpu_load_throughput', cpu_load_results)
        self.get_logger().info('CPU load throughput test completed')
    
    def start_discovery_overhead_test(self):
        """Test DDS discovery overhead with rapid node startup/shutdown"""
        if self.current_test_active:
            self.get_logger().warn('Test already active, skipping discovery overhead test')
            return
            
        self.current_test_active = True
        self.get_logger().info('Starting DDS discovery overhead test')
        
        # This test measures the impact of dynamic node creation/destruction on throughput
        topic_name = 'discovery_overhead'
        publisher, subscriber = self.create_test_topic_pair(topic_name)
        
        # Baseline measurement without node churn
        self.get_logger().info('Measuring baseline throughput without node churn')
        
        baseline_rate = 50  # Hz - moderate rate for baseline
        timer_period = 1.0 / baseline_rate
        baseline_duration = 30.0  # seconds
        
        # Reset counters
        with self.test_lock:
            self.message_counters[topic_name] = {'sent': 0, 'received': 0, 'lost': 0}
            self.latency_measurements[topic_name] = []
        
        # Start baseline publishing
        baseline_timer = self.create_timer(
            timer_period,
            lambda: self.publish_test_message(topic_name, publisher)
        )
        
        time.sleep(baseline_duration)
        baseline_timer.destroy()
        
        # Collect baseline results
        with self.test_lock:
            baseline_sent = self.message_counters[topic_name]['sent']
            baseline_received = self.message_counters[topic_name]['received']
            baseline_latencies = self.latency_measurements[topic_name].copy()
        
        baseline_throughput = baseline_received / baseline_duration
        baseline_latency = statistics.mean(baseline_latencies) if baseline_latencies else 0.0
        
        self.get_logger().info(f'Baseline: {baseline_throughput:.1f} Hz, {baseline_latency*1000:.2f}ms latency')
        
        # Test with node churn
        self.get_logger().info('Testing throughput with rapid node startup/shutdown')
        
        # Reset counters for churn test
        with self.test_lock:
            self.message_counters[topic_name] = {'sent': 0, 'received': 0, 'lost': 0}
            self.latency_measurements[topic_name] = []
        
        churn_duration = 60.0  # seconds
        node_spawn_rate = 2.0  # Hz - spawn/kill nodes every 0.5 seconds
        max_dummy_nodes = 10  # maximum number of dummy nodes to create
        
        # Start message publishing during churn test
        churn_timer = self.create_timer(
            timer_period,
            lambda: self.publish_test_message(topic_name, publisher)
        )
        
        # Simulate node churn by creating and destroying dummy publishers/subscribers
        dummy_nodes = []
        churn_start_time = time.time()
        node_creation_count = 0
        node_destruction_count = 0
        
        while time.time() - churn_start_time < churn_duration:
            try:
                # Create dummy node
                if len(dummy_nodes) < max_dummy_nodes:
                    dummy_topic = f'dummy_discovery_{node_creation_count}'
                    dummy_pub = self.create_publisher(String, dummy_topic, 10)
                    dummy_sub = self.create_subscription(String, dummy_topic, lambda msg: None, 10)
                    dummy_nodes.append((dummy_pub, dummy_sub))
                    node_creation_count += 1
                    
                # Destroy oldest dummy node
                if dummy_nodes and len(dummy_nodes) > 2:
                    old_pub, old_sub = dummy_nodes.pop(0)
                    try:
                        self.destroy_publisher(old_pub)
                        self.destroy_subscription(old_sub)
                        node_destruction_count += 1
                    except Exception as e:
                        self.get_logger().debug(f'Error destroying dummy node: {e}')
                
                # Wait before next churn event
                time.sleep(1.0 / node_spawn_rate)
                
            except Exception as e:
                self.get_logger().debug(f'Error in node churn: {e}')
                break
        
        churn_timer.destroy()
        
        # Clean up remaining dummy nodes
        for dummy_pub, dummy_sub in dummy_nodes:
            try:
                self.destroy_publisher(dummy_pub)
                self.destroy_subscription(dummy_sub)
            except Exception as e:
                self.get_logger().debug(f'Error cleaning up dummy node: {e}')
        
        # Collect churn test results
        with self.test_lock:
            churn_sent = self.message_counters[topic_name]['sent']
            churn_received = self.message_counters[topic_name]['received']
            churn_latencies = self.latency_measurements[topic_name].copy()
        
        churn_throughput = churn_received / churn_duration
        churn_latency = statistics.mean(churn_latencies) if churn_latencies else 0.0
        
        # Calculate overhead metrics
        throughput_degradation = (baseline_throughput - churn_throughput) / baseline_throughput if baseline_throughput > 0 else 0
        latency_increase = churn_latency - baseline_latency
        
        discovery_results = {
            'baseline': {
                'duration': baseline_duration,
                'throughput_hz': baseline_throughput,
                'avg_latency_ms': baseline_latency * 1000,
                'messages_sent': baseline_sent,
                'messages_received': baseline_received
            },
            'with_node_churn': {
                'duration': churn_duration,
                'throughput_hz': churn_throughput,
                'avg_latency_ms': churn_latency * 1000,
                'messages_sent': churn_sent,
                'messages_received': churn_received,
                'nodes_created': node_creation_count,
                'nodes_destroyed': node_destruction_count,
                'node_spawn_rate_hz': node_spawn_rate
            },
            'overhead_analysis': {
                'throughput_degradation_percent': throughput_degradation * 100,
                'latency_increase_ms': latency_increase * 1000,
                'discovery_impact_score': (throughput_degradation + (latency_increase / baseline_latency if baseline_latency > 0 else 0)) / 2
            }
        }
        
        self.test_results['discovery_overhead'] = discovery_results
        self.current_test_active = False
        
        self.publish_test_results('discovery_overhead', discovery_results)
        
        self.get_logger().info(f'Discovery overhead test completed:')
        self.get_logger().info(f'  Throughput degradation: {throughput_degradation*100:.1f}%')
        self.get_logger().info(f'  Latency increase: {latency_increase*1000:.2f}ms')
        self.get_logger().info(f'  Nodes created/destroyed: {node_creation_count}/{node_destruction_count}')
    
    def publish_test_message(self, topic_name: str, publisher):
        """Publish a test message with timestamp and payload"""
        payload_size = self.get_parameter('message_payload_size').value
        
        # Create message with timestamp and padding
        message_data = {
            'timestamp': time.time(),
            'sequence': self.message_counters[topic_name]['sent'],
            'payload': 'x' * max(0, payload_size - 100)  # Padding to reach desired size
        }
        
        msg = String()
        msg.data = json.dumps(message_data)
        
        publisher.publish(msg)
        
        with self.test_lock:
            self.message_counters[topic_name]['sent'] += 1
    
    def publish_test_results(self, test_name: str, results: dict):
        """Publish test results"""
        result_msg = String()
        result_data = {
            'test_name': test_name,
            'timestamp': time.time(),
            'results': results
        }
        result_msg.data = json.dumps(result_data, indent=2)
        
        self.results_publisher.publish(result_msg)
        self.get_logger().info(f'Published results for test: {test_name}')
    
    def publish_current_results(self):
        """Publish all current test results"""
        if self.test_results:
            result_msg = String()
            result_data = {
                'all_test_results': self.test_results,
                'timestamp': time.time()
            }
            result_msg.data = json.dumps(result_data, indent=2)
            self.results_publisher.publish(result_msg)
    
    def stop_current_test(self):
        """Stop any currently running test"""
        self.current_test_active = False
        self.get_logger().info('Test stopped by external command')

def main(args=None):
    rclpy.init(args=args)
    
    node = ThroughputTester()
    
    def signal_handler(signum, frame):
        node.get_logger().info('Shutdown signal received')
        node.stop_current_test()
        rclpy.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()

if __name__ == '__main__':
    main()