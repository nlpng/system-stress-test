#!/usr/bin/env python3
"""
Stress Orchestrator Node

Central coordinator for managing complex ROS 2 stress test scenarios.
Orchestrates multiple stress components (CPU, memory, message publishers/subscribers)
to execute coordinated test scenarios with precise timing and parameter control.
"""

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_msgs.msg import String, Bool, Int64, Float64
from std_srvs.srv import SetBool, Trigger
import json
import time
import threading
from collections import defaultdict
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import subprocess
import os
import signal


@dataclass
class ScenarioPhase:
    """Definition of a single phase in a stress test scenario."""
    name: str
    duration: float
    parameters: Dict[str, Any]
    description: str


@dataclass
class TestScenario:
    """Complete stress test scenario definition."""
    name: str
    description: str
    phases: List[ScenarioPhase]
    total_duration: float
    requires_cpu_stress: bool = False
    requires_memory_stress: bool = False
    requires_message_stress: bool = False
    requires_throughput_stress: bool = False


class StressOrchestrator(Node):
    """Central orchestrator for coordinated stress testing scenarios."""
    
    def __init__(self):
        super().__init__('stress_orchestrator')
        
        # Declare parameters
        self.declare_parameter('default_scenario', 'baseline')
        self.declare_parameter('auto_start', False)
        self.declare_parameter('status_interval', 5.0)
        self.declare_parameter('cleanup_on_shutdown', True)
        self.declare_parameter('cpu_stress_module_path', 'sys_stress_node.cpu_stress')
        self.declare_parameter('memory_stress_module_path', 'sys_stress_node.memory_stress')
        self.declare_parameter('max_scenario_duration', 3600.0)  # 1 hour safety limit
        self.declare_parameter('auto_baseline_before_stress', True)
        self.declare_parameter('baseline_duration', 120.0)  # 2 minutes baseline
        self.declare_parameter('require_baseline_validation', True)
        
        # Initialize state
        self.current_scenario = None
        self.current_phase_index = 0
        self.scenario_start_time = None
        self.phase_start_time = None
        self.is_running = False
        self.shutdown_requested = False
        
        # Active process tracking
        self.active_processes = {}
        self.node_status = defaultdict(dict)
        
        # Baseline measurement state
        self.baseline_completed = False
        self.baseline_summary = None
        self.baseline_client_available = False
        
        # Thread safety
        self.orchestrator_lock = threading.Lock()
        
        # Define built-in scenarios
        self._define_scenarios()
        
        # Setup ROS 2 interfaces
        self._setup_services()
        self._setup_publishers()
        self._setup_subscribers()
        
        # Setup monitoring timer
        status_interval = self.get_parameter('status_interval').value
        self.status_timer = self.create_timer(status_interval, self._monitor_scenario_progress)
        
        # Check for baseline collector availability
        self._check_baseline_availability()
        
        # Auto-start if configured
        if self.get_parameter('auto_start').value:
            default_scenario = self.get_parameter('default_scenario').value
            self._start_scenario_async(default_scenario)
        
        self.get_logger().info("StressOrchestrator initialized")
        self.get_logger().info(f"  Available scenarios: {list(self.scenarios.keys())}")
        self.get_logger().info(f"  Auto-start: {self.get_parameter('auto_start').value}")
        
    def _define_scenarios(self):
        """Define built-in stress test scenarios."""
        self.scenarios = {}
        
        # Pure baseline measurement (no artificial stress at all)
        self.scenarios['pure_baseline'] = TestScenario(
            name='pure_baseline',
            description='Pure baseline measurement with zero artificial stress',
            phases=[
                ScenarioPhase(
                    name='system_baseline',
                    duration=180.0,
                    parameters={
                        'baseline_only': True,
                        'auto_save': True
                    },
                    description='Measure pure system baseline with no artificial load'
                )
            ],
            total_duration=180.0,
            requires_message_stress=False,
            requires_cpu_stress=False,
            requires_memory_stress=False
        )
        
        # Light load baseline (minimal message stress for ROS 2 baseline)
        self.scenarios['light_baseline'] = TestScenario(
            name='light_baseline',
            description='Baseline measurement with minimal ROS 2 message load',
            phases=[
                ScenarioPhase(
                    name='ros2_baseline',
                    duration=120.0,
                    parameters={
                        'message_rate': 1.0,
                        'payload_size': 512,
                        'message_type': 'string',
                        'cpu_intensity': 0.0,
                        'memory_usage': 0
                    },
                    description='Measure ROS 2 baseline with 1Hz small messages'
                )
            ],
            total_duration=120.0,
            requires_message_stress=True
        )
        
        # High throughput message stress
        self.scenarios['high_throughput'] = TestScenario(
            name='high_throughput',
            description='Progressive message throughput stress testing',
            phases=[
                ScenarioPhase(
                    name='ramp_up',
                    duration=30.0,
                    parameters={
                        'message_rate': 100.0,
                        'payload_size': 1024,
                        'message_type': 'string'
                    },
                    description='Ramp up to 100Hz'
                ),
                ScenarioPhase(
                    name='high_rate',
                    duration=60.0,
                    parameters={
                        'message_rate': 1000.0,
                        'payload_size': 1024,
                        'message_type': 'bytes'
                    },
                    description='Sustain 1kHz message rate'
                ),
                ScenarioPhase(
                    name='burst_test',
                    duration=30.0,
                    parameters={
                        'message_rate': 5000.0,
                        'payload_size': 1024,
                        'message_type': 'twist',
                        'burst_mode': True
                    },
                    description='Burst mode at 5kHz'
                )
            ],
            total_duration=120.0,
            requires_message_stress=True
        )
        
        # Sensor message types stress test
        self.scenarios['sensor_messages'] = TestScenario(
            name='sensor_messages',
            description='Test realistic sensor message types performance',
            phases=[
                ScenarioPhase(
                    name='image_stress',
                    duration=45.0,
                    parameters={
                        'message_rate': 30.0,
                        'message_type': 'image',
                        'image_width': 640,
                        'image_height': 480,
                        'image_encoding': 'rgb8'
                    },
                    description='VGA RGB images at 30Hz'
                ),
                ScenarioPhase(
                    name='pointcloud_stress',
                    duration=45.0,
                    parameters={
                        'message_rate': 10.0,
                        'message_type': 'pointcloud2',
                        'pointcloud_points': 50000
                    },
                    description='50k point clouds at 10Hz'
                ),
                ScenarioPhase(
                    name='laserscan_stress',
                    duration=30.0,
                    parameters={
                        'message_rate': 40.0,
                        'message_type': 'laserscan',
                        'laserscan_ranges': 720
                    },
                    description='720-point laser scans at 40Hz'
                )
            ],
            total_duration=120.0,
            requires_message_stress=True
        )
        
        # Large payload stress
        self.scenarios['large_payload'] = TestScenario(
            name='large_payload',
            description='Progressive payload size stress testing with custom large messages',
            phases=[
                ScenarioPhase(
                    name='small_messages',
                    duration=30.0,
                    parameters={
                        'message_rate': 50.0,
                        'payload_size': 1024,
                        'message_type': 'string'
                    },
                    description='1KB string messages at 50Hz'
                ),
                ScenarioPhase(
                    name='medium_messages',
                    duration=30.0,
                    parameters={
                        'message_rate': 25.0,
                        'payload_size': 102400,  # 100KB
                        'message_type': 'custom_large',
                        'custom_payload_fields': 1000
                    },
                    description='100KB custom structured messages at 25Hz'
                ),
                ScenarioPhase(
                    name='large_messages',
                    duration=60.0,
                    parameters={
                        'message_rate': 5.0,
                        'payload_size': 1048576,  # 1MB
                        'message_type': 'custom_large',
                        'custom_payload_fields': 10000
                    },
                    description='1MB custom structured messages at 5Hz'
                )
            ],
            total_duration=120.0,
            requires_message_stress=True
        )
        
        # Dynamic message type switching scenario
        self.scenarios['dynamic_types'] = TestScenario(
            name='dynamic_types',
            description='Test dynamic switching between different message types',
            phases=[
                ScenarioPhase(
                    name='dynamic_switching',
                    duration=120.0,
                    parameters={
                        'message_rate': 20.0,
                        'dynamic_type_switching': True,
                        'type_switch_interval': 10.0,
                        'payload_size': 4096
                    },
                    description='Switch message types every 10 seconds'
                )
            ],
            total_duration=120.0,
            requires_message_stress=True
        )
        
        # CPU stress scenario
        self.scenarios['cpu_stress'] = TestScenario(
            name='cpu_stress',
            description='Progressive CPU stress with message monitoring',
            phases=[
                ScenarioPhase(
                    name='light_cpu',
                    duration=30.0,
                    parameters={
                        'cpu_intensity': 0.25,
                        'message_rate': 10.0,
                        'payload_size': 1024
                    },
                    description='25% CPU load'
                ),
                ScenarioPhase(
                    name='medium_cpu',
                    duration=30.0,
                    parameters={
                        'cpu_intensity': 0.50,
                        'message_rate': 10.0,
                        'payload_size': 1024
                    },
                    description='50% CPU load'
                ),
                ScenarioPhase(
                    name='high_cpu',
                    duration=60.0,
                    parameters={
                        'cpu_intensity': 0.80,
                        'message_rate': 10.0,
                        'payload_size': 1024
                    },
                    description='80% CPU load'
                )
            ],
            total_duration=120.0,
            requires_cpu_stress=True,
            requires_message_stress=True
        )
        
        # Memory stress scenario
        self.scenarios['memory_stress'] = TestScenario(
            name='memory_stress',
            description='Progressive memory stress with message monitoring',
            phases=[
                ScenarioPhase(
                    name='small_memory',
                    duration=30.0,
                    parameters={
                        'memory_usage': 536870912,  # 512MB
                        'message_rate': 10.0,
                        'payload_size': 1024
                    },
                    description='512MB memory allocation'
                ),
                ScenarioPhase(
                    name='large_memory',
                    duration=60.0,
                    parameters={
                        'memory_usage': 2147483648,  # 2GB
                        'message_rate': 10.0,
                        'payload_size': 1024
                    },
                    description='2GB memory allocation'
                )
            ],
            total_duration=90.0,
            requires_memory_stress=True,
            requires_message_stress=True
        )
        
        # Combined stress scenario
        self.scenarios['system_overload'] = TestScenario(
            name='system_overload',
            description='Combined CPU, memory, and message stress',
            phases=[
                ScenarioPhase(
                    name='baseline_combined',
                    duration=30.0,
                    parameters={
                        'cpu_intensity': 0.1,
                        'memory_usage': 268435456,  # 256MB
                        'message_rate': 50.0,
                        'payload_size': 1024
                    },
                    description='Light combined load'
                ),
                ScenarioPhase(
                    name='moderate_combined',
                    duration=60.0,
                    parameters={
                        'cpu_intensity': 0.5,
                        'memory_usage': 1073741824,  # 1GB
                        'message_rate': 500.0,
                        'payload_size': 4096
                    },
                    description='Moderate combined load'
                ),
                ScenarioPhase(
                    name='extreme_combined',
                    duration=30.0,
                    parameters={
                        'cpu_intensity': 0.8,
                        'memory_usage': 2147483648,  # 2GB
                        'message_rate': 1000.0,
                        'payload_size': 8192
                    },
                    description='Extreme combined load'
                )
            ],
            total_duration=120.0,
            requires_cpu_stress=True,
            requires_memory_stress=True,
            requires_message_stress=True
        )
        
        # Throughput stress testing scenarios
        self.scenarios['throughput_progression'] = TestScenario(
            name='throughput_progression',
            description='Progressive throughput testing from 1Hz to 10kHz',
            phases=[
                ScenarioPhase(
                    name='frequency_test',
                    duration=60.0,
                    parameters={
                        'throughput_test': 'frequency_progression',
                        'test_frequencies': [1, 10, 100, 1000, 10000],
                        'test_duration': 10.0
                    },
                    description='Test frequency progression'
                )
            ],
            total_duration=60.0,
            requires_throughput_stress=True
        )
        
        self.scenarios['sustainable_rate'] = TestScenario(
            name='sustainable_rate',
            description='Find maximum sustainable message rate',
            phases=[
                ScenarioPhase(
                    name='rate_discovery',
                    duration=120.0,
                    parameters={
                        'throughput_test': 'sustainable_rate',
                        'loss_tolerance': 0.05
                    },
                    description='Binary search for max sustainable rate'
                )
            ],
            total_duration=120.0,
            requires_throughput_stress=True
        )
        
        self.scenarios['queue_overflow'] = TestScenario(
            name='queue_overflow',
            description='Test subscriber queue overflow and recovery',
            phases=[
                ScenarioPhase(
                    name='overflow_test',
                    duration=60.0,
                    parameters={
                        'throughput_test': 'queue_overflow',
                        'overflow_rate': 1000,
                        'recovery_rate': 10
                    },
                    description='Test queue overflow behavior'
                )
            ],
            total_duration=60.0,
            requires_throughput_stress=True
        )
        
        self.scenarios['burst_patterns'] = TestScenario(
            name='burst_patterns',
            description='Test burst message patterns',
            phases=[
                ScenarioPhase(
                    name='burst_test',
                    duration=90.0,
                    parameters={
                        'throughput_test': 'burst_pattern',
                        'low_rate': 1,
                        'high_rate': 1000,
                        'cycle_duration': 5.0,
                        'num_cycles': 3
                    },
                    description='Test burst rate patterns'
                )
            ],
            total_duration=90.0,
            requires_throughput_stress=True
        )
        
        self.scenarios['cpu_throughput_matrix'] = TestScenario(
            name='cpu_throughput_matrix',
            description='Test throughput under various CPU loads',
            phases=[
                ScenarioPhase(
                    name='cpu_load_test',
                    duration=120.0,
                    parameters={
                        'throughput_test': 'cpu_load_throughput',
                        'cpu_levels': [0, 25, 50, 75, 90],
                        'test_frequency': 100,
                        'test_duration': 10.0
                    },
                    description='Test throughput under CPU stress'
                )
            ],
            total_duration=120.0,
            requires_throughput_stress=True,
            requires_cpu_stress=True
        )
        
    def _setup_services(self):
        """Setup ROS 2 services for orchestrator control."""
        # Scenario control services
        self.start_scenario_srv = self.create_service(
            String, 'start_scenario', self._start_scenario_service
        )
        self.stop_scenario_srv = self.create_service(
            Trigger, 'stop_scenario', self._stop_scenario_service
        )
        self.list_scenarios_srv = self.create_service(
            Trigger, 'list_scenarios', self._list_scenarios_service
        )
        self.get_status_srv = self.create_service(
            Trigger, 'get_orchestrator_status', self._get_status_service
        )
        
    def _setup_publishers(self):
        """Setup ROS 2 publishers for status and control."""
        # Status and progress publishing
        self.scenario_status_pub = self.create_publisher(
            String, 'scenario_status', 10
        )
        self.phase_progress_pub = self.create_publisher(
            String, 'phase_progress', 10
        )
        self.orchestrator_commands_pub = self.create_publisher(
            String, 'orchestrator_commands', 10
        )
        
    def _setup_subscribers(self):
        """Setup ROS 2 subscribers for monitoring stress nodes."""
        # Monitor aggregated metrics from MetricsCollector
        self.metrics_subscriber = self.create_subscription(
            String, 'aggregated_metrics', self._metrics_callback, 10
        )
        
        # Monitor alerts from stress test components
        self.alerts_subscriber = self.create_subscription(
            String, 'performance_alerts', self._alerts_callback, 10
        )
        
        # Monitor baseline status
        self.baseline_status_subscriber = self.create_subscription(
            String, 'baseline_status', self._baseline_status_callback, 10
        )
        
        # Subscribe to baseline metrics
        self.baseline_metrics_subscriber = self.create_subscription(
            String, 'baseline_metrics', self._baseline_metrics_callback, 10
        )
        
        # Subscribe to throughput test results
        self.throughput_results_subscriber = self.create_subscription(
            String, 'throughput_test_results', self._throughput_results_callback, 10
        )
        
    def _start_scenario_service(self, request, response):
        """Service callback to start a stress test scenario."""
        try:
            scenario_name = request.data
            success = self.start_scenario(scenario_name)
            
            if success:
                response.data = f"Started scenario: {scenario_name}"
                self.get_logger().info(f"Service request: started scenario '{scenario_name}'")
            else:
                response.data = f"Failed to start scenario: {scenario_name}"
                self.get_logger().error(f"Service request: failed to start scenario '{scenario_name}'")
                
        except Exception as e:
            response.data = f"Error starting scenario: {e}"
            self.get_logger().error(f"Service error: {e}")
            
        return response
        
    def _stop_scenario_service(self, request, response):
        """Service callback to stop current scenario."""
        try:
            success = self.stop_scenario()
            response.success = success
            response.message = "Scenario stopped successfully" if success else "No scenario running"
            
        except Exception as e:
            response.success = False
            response.message = f"Error stopping scenario: {e}"
            self.get_logger().error(f"Service error: {e}")
            
        return response
        
    def _list_scenarios_service(self, request, response):
        """Service callback to list available scenarios."""
        try:
            scenarios_info = {}
            for name, scenario in self.scenarios.items():
                scenarios_info[name] = {
                    'description': scenario.description,
                    'duration': scenario.total_duration,
                    'phases': len(scenario.phases),
                    'requires_cpu': scenario.requires_cpu_stress,
                    'requires_memory': scenario.requires_memory_stress,
                    'requires_message': scenario.requires_message_stress,
                    'requires_throughput': scenario.requires_throughput_stress
                }
            
            response.success = True
            response.message = json.dumps(scenarios_info, indent=2)
            
        except Exception as e:
            response.success = False
            response.message = f"Error listing scenarios: {e}"
            
        return response
        
    def _get_status_service(self, request, response):
        """Service callback to get orchestrator status."""
        try:
            status = self.get_orchestrator_status()
            response.success = True
            response.message = json.dumps(status, indent=2, default=str)
            
        except Exception as e:
            response.success = False
            response.message = f"Error getting status: {e}"
            
        return response
        
    def start_scenario(self, scenario_name: str) -> bool:
        """Start a stress test scenario with optional baseline measurement."""
        with self.orchestrator_lock:
            if self.is_running:
                self.get_logger().warn(f"Cannot start '{scenario_name}': scenario already running")
                return False
                
            if scenario_name not in self.scenarios:
                self.get_logger().error(f"Unknown scenario: {scenario_name}")
                return False
            
            # Check if we need baseline measurement first
            if self.get_parameter('auto_baseline_before_stress').value and not self.baseline_completed:
                if self._start_baseline_measurement():
                    # Baseline measurement started, scenario will start after completion
                    self._pending_scenario = scenario_name
                    return True
                else:
                    self.get_logger().warn("Failed to start baseline measurement, proceeding without baseline")
                    
            return self._start_scenario_internal(scenario_name)
            
    def _start_scenario_internal(self, scenario_name: str) -> bool:
        """Internal method to start scenario without baseline check."""
        self.current_scenario = self.scenarios[scenario_name]
        self.current_phase_index = 0
        self.scenario_start_time = time.time()
        self.is_running = True
        self.shutdown_requested = False
        
        self.get_logger().info(f"Starting scenario: {scenario_name}")
        self.get_logger().info(f"  Description: {self.current_scenario.description}")
        self.get_logger().info(f"  Duration: {self.current_scenario.total_duration}s")
        self.get_logger().info(f"  Phases: {len(self.current_scenario.phases)}")
        
        if self.baseline_summary:
            self.get_logger().info(f"  Baseline available: {self.baseline_summary.get('measurement_quality', 'unknown')} quality")
        
        # Start the first phase
        success = self._start_current_phase()
        
        if success:
            self._publish_scenario_status('started')
        else:
            self.is_running = False
            self.current_scenario = None
            
        return success
            
    def stop_scenario(self) -> bool:
        """Stop the current stress test scenario."""
        with self.orchestrator_lock:
            if not self.is_running:
                return False
                
            self.get_logger().info("Stopping current scenario...")
            self.shutdown_requested = True
            
            # Stop all active stress processes
            self._cleanup_all_processes()
            
            # Reset state
            self.is_running = False
            scenario_name = self.current_scenario.name if self.current_scenario else "unknown"
            self.current_scenario = None
            self.current_phase_index = 0
            
            self.get_logger().info(f"Scenario '{scenario_name}' stopped")
            self._publish_scenario_status('stopped')
            
            return True
            
    def _start_current_phase(self) -> bool:
        """Start the current phase of the scenario."""
        if not self.current_scenario or self.current_phase_index >= len(self.current_scenario.phases):
            return False
            
        phase = self.current_scenario.phases[self.current_phase_index]
        self.phase_start_time = time.time()
        
        self.get_logger().info(f"Starting phase {self.current_phase_index + 1}/{len(self.current_scenario.phases)}: {phase.name}")
        self.get_logger().info(f"  Description: {phase.description}")
        self.get_logger().info(f"  Duration: {phase.duration}s")
        self.get_logger().info(f"  Parameters: {phase.parameters}")
        
        # Handle pure baseline scenario (no stress components)
        if phase.parameters.get('baseline_only', False):
            success = self._start_pure_baseline_measurement(phase.parameters)
        else:
            # Start required stress components
            success = True
            
            if self.current_scenario.requires_cpu_stress:
                success &= self._start_cpu_stress(phase.parameters)
                
            if self.current_scenario.requires_memory_stress:
                success &= self._start_memory_stress(phase.parameters)
                
            if self.current_scenario.requires_message_stress:
                success &= self._start_message_stress(phase.parameters)
                
            if self.current_scenario.requires_throughput_stress:
                success &= self._start_throughput_stress(phase.parameters)
            
        if success:
            self._publish_phase_progress()
        else:
            self.get_logger().error(f"Failed to start phase: {phase.name}")
            
        return success
        
    def _start_pure_baseline_measurement(self, parameters: Dict[str, Any]) -> bool:
        """Start pure baseline measurement without any stress components."""
        try:
            self.get_logger().info("Starting pure baseline measurement...")
            
            # Send command to baseline collector to start measurement
            baseline_duration = self.current_scenario.phases[self.current_phase_index].duration
            
            self._publish_command({
                'target': 'baseline_collector',
                'action': 'start_measurement',
                'parameters': {
                    'duration': baseline_duration,
                    'auto_save': parameters.get('auto_save', True)
                }
            })
            
            self.get_logger().info(f"Pure baseline measurement requested for {baseline_duration}s")
            return True
            
        except Exception as e:
            self.get_logger().error(f"Error starting pure baseline measurement: {e}")
            return False
        
    def _start_cpu_stress(self, parameters: Dict[str, Any]) -> bool:
        """Start CPU stress component."""
        try:
            cpu_intensity = parameters.get('cpu_intensity', 0.5)
            duration = self.current_scenario.phases[self.current_phase_index].duration
            
            # Import and use CPU stress module
            from . import cpu_stress
            
            if 'cpu_stress' not in self.active_processes:
                self.active_processes['cpu_stress'] = cpu_stress.CPUStressTester()
                
            success = self.active_processes['cpu_stress'].start_stress_test(
                intensity=cpu_intensity,
                duration=duration
            )
            
            if success:
                self.get_logger().info(f"Started CPU stress: {cpu_intensity:.0%} intensity")
            else:
                self.get_logger().error("Failed to start CPU stress")
                
            return success
            
        except Exception as e:
            self.get_logger().error(f"Error starting CPU stress: {e}")
            return False
            
    def _start_memory_stress(self, parameters: Dict[str, Any]) -> bool:
        """Start memory stress component."""
        try:
            memory_usage = parameters.get('memory_usage', 1024 * 1024 * 1024)  # 1GB default
            duration = self.current_scenario.phases[self.current_phase_index].duration
            
            # Import and use memory stress module
            from . import memory_stress
            
            if 'memory_stress' not in self.active_processes:
                self.active_processes['memory_stress'] = memory_stress.MemoryStressTester()
                
            success = self.active_processes['memory_stress'].start_stress_test(
                target_memory=memory_usage,
                duration=duration
            )
            
            if success:
                memory_mb = memory_usage / (1024 * 1024)
                self.get_logger().info(f"Started memory stress: {memory_mb:.0f}MB allocation")
            else:
                self.get_logger().error("Failed to start memory stress")
                
            return success
            
        except Exception as e:
            self.get_logger().error(f"Error starting memory stress: {e}")
            return False
            
    def _start_message_stress(self, parameters: Dict[str, Any]) -> bool:
        """Start message stress components."""
        try:
            # Update publisher parameters including message type specific parameters
            pub_params = [
                Parameter('publish_rate', Parameter.Type.DOUBLE, 
                         parameters.get('message_rate', 10.0)),
                Parameter('payload_size', Parameter.Type.INTEGER, 
                         parameters.get('payload_size', 1024)),
                Parameter('burst_mode', Parameter.Type.BOOL, 
                         parameters.get('burst_mode', False)),
                Parameter('message_type', Parameter.Type.STRING,
                         parameters.get('message_type', 'string'))
            ]
            
            # Add message type specific parameters
            if 'image_width' in parameters:
                pub_params.append(Parameter('image_width', Parameter.Type.INTEGER, parameters['image_width']))
            if 'image_height' in parameters:
                pub_params.append(Parameter('image_height', Parameter.Type.INTEGER, parameters['image_height']))
            if 'image_encoding' in parameters:
                pub_params.append(Parameter('image_encoding', Parameter.Type.STRING, parameters['image_encoding']))
            if 'pointcloud_points' in parameters:
                pub_params.append(Parameter('pointcloud_points', Parameter.Type.INTEGER, parameters['pointcloud_points']))
            if 'laserscan_ranges' in parameters:
                pub_params.append(Parameter('laserscan_ranges', Parameter.Type.INTEGER, parameters['laserscan_ranges']))
            if 'custom_payload_fields' in parameters:
                pub_params.append(Parameter('custom_payload_fields', Parameter.Type.INTEGER, parameters['custom_payload_fields']))
            if 'dynamic_type_switching' in parameters:
                pub_params.append(Parameter('dynamic_type_switching', Parameter.Type.BOOL, parameters['dynamic_type_switching']))
            if 'type_switch_interval' in parameters:
                pub_params.append(Parameter('type_switch_interval', Parameter.Type.DOUBLE, parameters['type_switch_interval']))
            
            # Send parameter updates to publisher
            self._publish_command({
                'target': 'message_stress_publisher',
                'action': 'update_parameters',
                'parameters': {p.name: p.value for p in pub_params}
            })
            
            msg_type = parameters.get('message_type', 'string')
            self.get_logger().info(f"Updated message stress: {parameters.get('message_rate', 10.0)}Hz, "
                                 f"{parameters.get('payload_size', 1024)} bytes, type: {msg_type}")
            
            return True
            
        except Exception as e:
            self.get_logger().error(f"Error starting message stress: {e}")
            return False
            
    def _start_throughput_stress(self, parameters: Dict[str, Any]) -> bool:
        """Start throughput stress testing."""
        try:
            throughput_test = parameters.get('throughput_test', 'frequency_progression')
            
            # Send command to throughput tester
            command = {
                'target': 'throughput_tester',
                'action': 'start_test',
                'test_type': throughput_test,
                'parameters': parameters
            }
            
            # Format command for specific test types
            if throughput_test == 'frequency_progression':
                command_data = {
                    'command': 'start_frequency_test',
                    'frequencies': parameters.get('test_frequencies', [1, 10, 100, 1000, 10000]),
                    'test_duration': parameters.get('test_duration', 10.0)
                }
            elif throughput_test == 'sustainable_rate':
                command_data = {
                    'command': 'start_sustainable_rate_test',
                    'loss_tolerance': parameters.get('loss_tolerance', 0.05)
                }
            elif throughput_test == 'queue_overflow':
                command_data = {
                    'command': 'start_queue_overflow_test',
                    'overflow_rate': parameters.get('overflow_rate', 1000),
                    'recovery_rate': parameters.get('recovery_rate', 10)
                }
            elif throughput_test == 'burst_pattern':
                command_data = {
                    'command': 'start_burst_test',
                    'low_rate': parameters.get('low_rate', 1),
                    'high_rate': parameters.get('high_rate', 1000),
                    'cycle_duration': parameters.get('cycle_duration', 5.0),
                    'num_cycles': parameters.get('num_cycles', 3)
                }
            elif throughput_test == 'cpu_load_throughput':
                command_data = {
                    'command': 'start_cpu_load_test',
                    'cpu_levels': parameters.get('cpu_levels', [0, 25, 50, 75, 90]),
                    'test_frequency': parameters.get('test_frequency', 100),
                    'test_duration': parameters.get('test_duration', 10.0)
                }
            else:
                self.get_logger().error(f"Unknown throughput test type: {throughput_test}")
                return False
            
            # Publish command to throughput tester control topic
            self._publish_throughput_command(command_data)
            
            self.get_logger().info(f"Started throughput test: {throughput_test}")
            return True
            
        except Exception as e:
            self.get_logger().error(f"Error starting throughput stress: {e}")
            return False
            
    def _publish_throughput_command(self, command_data: Dict[str, Any]):
        """Publish command to throughput tester control topic."""
        try:
            # Create a one-time publisher for throughput control
            if not hasattr(self, '_throughput_control_pub'):
                self._throughput_control_pub = self.create_publisher(
                    String, 'throughput_test_control', 10
                )
            
            msg = String()
            msg.data = json.dumps(command_data)
            self._throughput_control_pub.publish(msg)
            
            self.get_logger().debug(f"Published throughput command: {command_data.get('command', 'unknown')}")
            
        except Exception as e:
            self.get_logger().error(f"Failed to publish throughput command: {e}")
            
    def _monitor_scenario_progress(self):
        """Monitor scenario progress and handle phase transitions."""
        if not self.is_running or self.shutdown_requested:
            return
            
        current_time = time.time()
        
        # Check if current phase is complete
        if self.phase_start_time:
            phase_elapsed = current_time - self.phase_start_time
            current_phase = self.current_scenario.phases[self.current_phase_index]
            
            if phase_elapsed >= current_phase.duration:
                self._transition_to_next_phase()
                
        # Check if entire scenario is complete
        if self.scenario_start_time:
            total_elapsed = current_time - self.scenario_start_time
            if total_elapsed >= self.current_scenario.total_duration:
                self._complete_scenario()
                
        # Publish progress update
        self._publish_phase_progress()
        
    def _transition_to_next_phase(self):
        """Transition to the next phase of the scenario."""
        self.current_phase_index += 1
        
        if self.current_phase_index >= len(self.current_scenario.phases):
            self._complete_scenario()
            return
            
        self.get_logger().info(f"Transitioning to phase {self.current_phase_index + 1}")
        
        # Stop current phase processes if needed
        self._cleanup_phase_processes()
        
        # Start next phase
        success = self._start_current_phase()
        
        if not success:
            self.get_logger().error("Failed to start next phase, stopping scenario")
            self.stop_scenario()
            
    def _complete_scenario(self):
        """Complete the current scenario."""
        if self.current_scenario:
            scenario_name = self.current_scenario.name
            total_time = time.time() - self.scenario_start_time
            
            self.get_logger().info(f"Scenario '{scenario_name}' completed in {total_time:.1f}s")
            
        self.stop_scenario()
        
    def _cleanup_phase_processes(self):
        """Cleanup processes specific to the current phase."""
        # Stop CPU and memory stress (they're phase-specific)
        if 'cpu_stress' in self.active_processes:
            try:
                self.active_processes['cpu_stress'].stop_stress_test()
            except Exception as e:
                self.get_logger().debug(f"Error stopping CPU stress: {e}")
                
        if 'memory_stress' in self.active_processes:
            try:
                self.active_processes['memory_stress'].stop_stress_test()
            except Exception as e:
                self.get_logger().debug(f"Error stopping memory stress: {e}")
                
    def _cleanup_all_processes(self):
        """Cleanup all active stress processes."""
        for name, process in self.active_processes.items():
            try:
                if hasattr(process, 'stop_stress_test'):
                    process.stop_stress_test()
                elif hasattr(process, 'terminate'):
                    process.terminate()
                self.get_logger().debug(f"Stopped process: {name}")
            except Exception as e:
                self.get_logger().debug(f"Error stopping {name}: {e}")
                
        self.active_processes.clear()
        
    def _publish_command(self, command: Dict[str, Any]):
        """Publish command to other stress test nodes."""
        try:
            msg = String()
            msg.data = json.dumps(command)
            self.orchestrator_commands_pub.publish(msg)
        except Exception as e:
            self.get_logger().error(f"Failed to publish command: {e}")
            
    def _publish_scenario_status(self, status: str):
        """Publish scenario status update."""
        try:
            status_data = {
                'status': status,
                'scenario': self.current_scenario.name if self.current_scenario else None,
                'timestamp': time.time()
            }
            
            msg = String()
            msg.data = json.dumps(status_data)
            self.scenario_status_pub.publish(msg)
            
        except Exception as e:
            self.get_logger().error(f"Failed to publish scenario status: {e}")
            
    def _publish_phase_progress(self):
        """Publish current phase progress."""
        if not self.is_running or not self.current_scenario:
            return
            
        try:
            current_time = time.time()
            current_phase = self.current_scenario.phases[self.current_phase_index]
            
            progress_data = {
                'scenario_name': self.current_scenario.name,
                'phase_index': self.current_phase_index,
                'phase_name': current_phase.name,
                'phase_description': current_phase.description,
                'total_phases': len(self.current_scenario.phases),
                'phase_elapsed': current_time - self.phase_start_time if self.phase_start_time else 0,
                'phase_duration': current_phase.duration,
                'phase_progress': min(1.0, (current_time - self.phase_start_time) / current_phase.duration) if self.phase_start_time else 0,
                'scenario_elapsed': current_time - self.scenario_start_time if self.scenario_start_time else 0,
                'scenario_duration': self.current_scenario.total_duration,
                'scenario_progress': min(1.0, (current_time - self.scenario_start_time) / self.current_scenario.total_duration) if self.scenario_start_time else 0,
                'timestamp': current_time
            }
            
            msg = String()
            msg.data = json.dumps(progress_data)
            self.phase_progress_pub.publish(msg)
            
        except Exception as e:
            self.get_logger().error(f"Failed to publish phase progress: {e}")
            
    def _metrics_callback(self, msg):
        """Handle metrics updates from MetricsCollector."""
        try:
            metrics_data = json.loads(msg.data)
            # Store latest metrics for status reporting
            self.node_status['metrics_collector'] = {
                'timestamp': time.time(),
                'data': metrics_data
            }
        except Exception as e:
            self.get_logger().debug(f"Error processing metrics: {e}")
            
    def _alerts_callback(self, msg):
        """Handle performance alerts."""
        try:
            alert_data = json.loads(msg.data)
            self.get_logger().warn(f"Performance Alert: {alert_data.get('message', 'Unknown alert')}")
            
            # Store alert for status reporting
            if 'alerts' not in self.node_status:
                self.node_status['alerts'] = []
            self.node_status['alerts'].append({
                'timestamp': time.time(),
                'alert': alert_data
            })
            
            # Keep only recent alerts
            cutoff = time.time() - 300  # 5 minutes
            self.node_status['alerts'] = [
                a for a in self.node_status['alerts'] 
                if a['timestamp'] > cutoff
            ]
            
        except Exception as e:
            self.get_logger().debug(f"Error processing alert: {e}")
            
    def get_orchestrator_status(self) -> Dict[str, Any]:
        """Get comprehensive orchestrator status."""
        current_time = time.time()
        
        status = {
            'is_running': self.is_running,
            'current_scenario': self.current_scenario.name if self.current_scenario else None,
            'available_scenarios': list(self.scenarios.keys()),
            'active_processes': list(self.active_processes.keys()),
            'node_status': dict(self.node_status)
        }
        
        if self.is_running and self.current_scenario:
            current_phase = self.current_scenario.phases[self.current_phase_index]
            status.update({
                'scenario_info': {
                    'name': self.current_scenario.name,
                    'description': self.current_scenario.description,
                    'total_duration': self.current_scenario.total_duration,
                    'elapsed': current_time - self.scenario_start_time if self.scenario_start_time else 0
                },
                'current_phase': {
                    'index': self.current_phase_index,
                    'name': current_phase.name,
                    'description': current_phase.description,
                    'duration': current_phase.duration,
                    'elapsed': current_time - self.phase_start_time if self.phase_start_time else 0,
                    'parameters': current_phase.parameters
                }
            })
            
        return status
        
    def _check_baseline_availability(self):
        """Check if baseline collector is available."""
        # This would typically involve checking for the baseline service
        # For now, we'll assume it's available if the baseline parameter is enabled
        self.baseline_client_available = self.get_parameter('auto_baseline_before_stress').value
        
    def _start_baseline_measurement(self) -> bool:
        """Start baseline measurement before stress testing."""
        if not self.baseline_client_available:
            return False
            
        try:
            baseline_duration = self.get_parameter('baseline_duration').value
            
            self.get_logger().info(f"Starting baseline measurement ({baseline_duration}s) before stress testing...")
            
            # In a real implementation, this would call the baseline service
            # For now, we'll simulate baseline completion
            self._simulate_baseline_measurement()
            
            return True
            
        except Exception as e:
            self.get_logger().error(f"Failed to start baseline measurement: {e}")
            return False
            
    def _simulate_baseline_measurement(self):
        """Simulate baseline measurement completion (for testing)."""
        # Create a simple baseline summary for testing
        self.baseline_summary = {
            'measurement_start': time.time(),
            'measurement_duration': self.get_parameter('baseline_duration').value,
            'measurement_quality': 'good',
            'system_stability_score': 0.85,
            'cpu_baseline': {'mean': 5.2, 'std': 1.1},
            'memory_baseline': {'mean': 45.0, 'std': 2.3},
            'warnings': []
        }
        
        self.baseline_completed = True
        
        # Start pending scenario if any
        if hasattr(self, '_pending_scenario'):
            scenario_name = self._pending_scenario
            delattr(self, '_pending_scenario')
            
            self.get_logger().info(f"Baseline completed, starting scenario: {scenario_name}")
            self._start_scenario_internal(scenario_name)
            
    def _baseline_status_callback(self, msg):
        """Handle baseline status updates."""
        try:
            status_data = json.loads(msg.data)
            status = status_data.get('status', '')
            
            if status == 'completed':
                self.baseline_completed = True
                self.get_logger().info("Baseline measurement completed")
                
                # Start pending scenario if any
                if hasattr(self, '_pending_scenario'):
                    scenario_name = self._pending_scenario
                    delattr(self, '_pending_scenario')
                    
                    self.get_logger().info(f"Starting delayed scenario: {scenario_name}")
                    self._start_scenario_internal(scenario_name)
                    
        except Exception as e:
            self.get_logger().debug(f"Error processing baseline status: {e}")
            
    def _baseline_metrics_callback(self, msg):
        """Handle baseline metrics updates."""
        try:
            metrics_data = json.loads(msg.data)
            
            # Store baseline summary when available
            if 'measurement_quality' in metrics_data:
                self.baseline_summary = metrics_data
                self.get_logger().info(f"Received baseline summary: {metrics_data.get('measurement_quality', 'unknown')} quality")
                
        except Exception as e:
            self.get_logger().debug(f"Error processing baseline metrics: {e}")
            
    def _throughput_results_callback(self, msg):
        """Handle throughput test results."""
        try:
            results_data = json.loads(msg.data)
            test_name = results_data.get('test_name', 'unknown')
            
            self.get_logger().info(f"Received throughput test results: {test_name}")
            
            # Store results for status reporting
            if 'throughput_results' not in self.node_status:
                self.node_status['throughput_results'] = {}
                
            self.node_status['throughput_results'][test_name] = {
                'timestamp': time.time(),
                'results': results_data.get('results', {})
            }
            
            # Log key metrics from the results
            if 'results' in results_data:
                results = results_data['results']
                if test_name == 'frequency_progression':
                    for freq, metrics in results.items():
                        if isinstance(metrics, dict):
                            loss_rate = metrics.get('loss_rate', 0) * 100
                            latency = metrics.get('avg_latency', 0) * 1000  # Convert to ms
                            self.get_logger().info(f"  {freq}Hz: {loss_rate:.1f}% loss, {latency:.2f}ms latency")
                elif test_name == 'sustainable_rate':
                    max_rate = results.get('max_sustainable_rate', 0)
                    self.get_logger().info(f"  Max sustainable rate: {max_rate}Hz")
                elif test_name == 'queue_overflow':
                    total_loss = results.get('total_loss_rate', 0) * 100
                    recovery_msgs = results.get('recovery_messages_received', 0)
                    self.get_logger().info(f"  Queue overflow: {total_loss:.1f}% loss, {recovery_msgs} recovery msgs")
            
        except Exception as e:
            self.get_logger().debug(f"Error processing throughput results: {e}")
            
    def compare_with_baseline(self, current_metrics: Dict[str, Any]) -> Dict[str, Any]:
        """Compare current performance with baseline."""
        if not self.baseline_summary:
            return {'error': 'No baseline available for comparison'}
            
        comparison = {
            'baseline_available': True,
            'baseline_quality': self.baseline_summary.get('measurement_quality', 'unknown'),
            'comparisons': {}
        }
        
        # Compare system metrics with baseline
        if 'system_metrics' in current_metrics and self.baseline_summary:
            system_current = current_metrics['system_metrics']
            
            # CPU comparison
            baseline_cpu = self.baseline_summary.get('cpu_baseline', {}).get('mean', 0)
            current_cpu = system_current.get('cpu_percent', 0)
            if baseline_cpu > 0:
                comparison['comparisons']['cpu'] = {
                    'baseline': baseline_cpu,
                    'current': current_cpu,
                    'change_percent': ((current_cpu - baseline_cpu) / baseline_cpu) * 100,
                    'status': 'elevated' if current_cpu > baseline_cpu * 1.5 else 'normal'
                }
                
            # Memory comparison
            baseline_memory = self.baseline_summary.get('memory_baseline', {}).get('mean', 0)
            current_memory = system_current.get('memory_percent', 0)
            if baseline_memory > 0:
                comparison['comparisons']['memory'] = {
                    'baseline': baseline_memory,
                    'current': current_memory,
                    'change_percent': ((current_memory - baseline_memory) / baseline_memory) * 100,
                    'status': 'elevated' if current_memory > baseline_memory * 1.3 else 'normal'
                }
                
        return comparison
        
    def _start_scenario_async(self, scenario_name: str):
        """Start scenario asynchronously (for auto-start)."""
        def start_delayed():
            time.sleep(2.0)  # Wait for node initialization
            
            # Check if baseline measurement is needed
            if self.get_parameter('auto_baseline_before_stress').value:
                time.sleep(5.0)  # Additional wait for baseline collector
                
            self.start_scenario(scenario_name)
            
        thread = threading.Thread(target=start_delayed)
        thread.daemon = True
        thread.start()
        
    def destroy_node(self):
        """Clean up resources."""
        if self.is_running:
            self.stop_scenario()
        super().destroy_node()


def main(args=None):
    """Main entry point for stress orchestrator."""
    rclpy.init(args=args)
    
    try:
        orchestrator_node = StressOrchestrator()
        rclpy.spin(orchestrator_node)
        
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'orchestrator_node' in locals():
            orchestrator_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()