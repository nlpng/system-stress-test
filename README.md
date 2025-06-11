# ROS 2 System Stress Test Node

A comprehensive ROS 2 humble package for stress testing system performance with CPU/memory stress, ROS 2 message communication stress, baseline measurement, and coordinated scenario execution.

## Overview

This package provides a complete stress testing ecosystem that can:
- **System Stress**: CPU and memory stress testing with configurable intensity
- **Message Stress**: ROS 2 message throughput and latency stress testing
- **Baseline Measurement**: Pure system baseline performance measurement
- **Scenario Orchestration**: Coordinated multi-component stress scenarios
- **Comprehensive Monitoring**: Real-time metrics collection and analysis
- **Safety Features**: Automatic shutdown on critical thresholds
- **Standalone Operation**: Run stress modules independently without ROS 2

## Package Structure

```
sys_stress_node/
├── package.xml                    # Package metadata and dependencies
├── setup.py                      # Python package setup
├── setup.cfg                     # Package configuration
├── resource/                     # Package resource marker
├── sys_stress_node/              # Python package
│   ├── __init__.py
│   ├── cpu_stress.py            # CPU stress testing module
│   ├── memory_stress.py         # Memory stress testing module
│   ├── system_monitor.py        # System monitoring module
│   ├── stress_node.py           # Main ROS 2 node
│   ├── message_stress_publisher.py  # Message stress publisher
│   ├── message_stress_subscriber.py # Message stress subscriber
│   ├── metrics_collector.py     # Central metrics aggregation
│   ├── baseline_collector.py    # Baseline performance measurement
│   └── stress_orchestrator.py   # Scenario coordination
├── launch/                      # Launch files
│   └── stress_test.launch.py
└── config/                      # Configuration files
    └── default_params.yaml
```

## Dependencies

### For ROS 2 Usage:
- ROS 2 humble
- rclpy
- std_msgs
- sensor_msgs
- geometry_msgs
- python3-psutil
- python3-numpy

### For Standalone Usage:
- Python 3.8+
- python3-psutil (install with: `pip3 install psutil`)
- python3-numpy (install with: `pip3 install numpy`)

## Building

### For ROS 2 Usage:
```bash
# Build the package
colcon build --packages-select sys_stress_node

# Source the workspace
source install/setup.bash
```

### For Standalone Usage:
```bash
# Install dependencies only
pip3 install psutil numpy

# No build required - run modules directly
```

## Core Components

### 1. System Stress Testing
- **CPU Stress**: Multiprocessing-based CPU load generation with precise intensity control
- **Memory Stress**: Progressive memory allocation with safety limits and cleanup
- **Real-time Monitoring**: Continuous system resource monitoring with psutil

### 2. Message Stress Testing
- **Advanced Message Types**: Support for string, bytes, Twist, Image, PointCloud2, LaserScan, and custom large payloads
- **Dynamic Type Switching**: Automatically cycle through different message types during testing
- **Realistic Data Generation**: Pre-cached sensor data with timestamp-based variations
- **Performance Metrics**: Comprehensive latency, throughput, and loss rate measurement

### 3. Baseline Performance Measurement
- **Pure System Baseline**: Measure system performance with zero artificial stress
- **Idle Validation**: Ensure system is truly idle before baseline measurement
- **Statistical Analysis**: Calculate comprehensive statistics with stability scoring
- **Quality Assessment**: Rate measurement quality and generate warnings

### 4. Scenario Orchestration
- **Built-in Scenarios**: 8 pre-defined test scenarios covering various stress patterns
- **Multi-Phase Execution**: Complex scenarios with automatic phase transitions
- **Parameter Coordination**: Synchronize parameters across multiple stress components
- **Baseline Integration**: Automatic baseline measurement before stress scenarios

### 5. Metrics Collection & Analysis
- **Central Aggregation**: Collect metrics from all stress test components
- **Advanced Analytics**: Trend detection, baseline comparison, performance alerts
- **Export Capabilities**: CSV/JSON export for external analysis
- **Real-time Monitoring**: Live metrics publishing and threshold monitoring

## Usage

### Standalone Usage (Without ROS 2)

#### CPU Stress Testing
```bash
# Basic CPU stress test
python3 src/sys_stress_node/sys_stress_node/cpu_stress.py

# Custom intensity and duration
python3 src/sys_stress_node/sys_stress_node/cpu_stress.py --intensity 0.5 --duration 30

# Verbose output with custom process count
python3 src/sys_stress_node/sys_stress_node/cpu_stress.py -i 0.8 -p 4 -v
```

#### Memory Stress Testing
```bash
# Basic memory stress test
python3 src/sys_stress_node/sys_stress_node/memory_stress.py

# Custom target and duration
python3 src/sys_stress_node/sys_stress_node/memory_stress.py --target 1024 --duration 60

# Verbose output with system info
python3 src/sys_stress_node/sys_stress_node/memory_stress.py -t 512 -v -s
```

### ROS 2 Usage

#### Basic Component Usage

```bash
# Run individual components
ros2 run sys_stress_node stress_node                    # System stress
ros2 run sys_stress_node message_stress_publisher       # Message publisher
ros2 run sys_stress_node message_stress_subscriber      # Message subscriber
ros2 run sys_stress_node metrics_collector              # Metrics collection
ros2 run sys_stress_node baseline_collector             # Baseline measurement
ros2 run sys_stress_node stress_orchestrator            # Scenario coordination
```

#### Scenario-Based Testing

```bash
# List available scenarios
ros2 service call /list_scenarios std_srvs/srv/Trigger

# Start a specific scenario
ros2 service call /start_scenario std_msgs/srv/String "data: 'high_throughput'"

# Stop current scenario
ros2 service call /stop_scenario std_srvs/srv/Trigger

# Get orchestrator status
ros2 service call /get_orchestrator_status std_srvs/srv/Trigger
```

#### Baseline Measurement

```bash
# Start baseline measurement
ros2 service call /start_baseline_measurement std_srvs/srv/Trigger

# Validate system is idle
ros2 service call /validate_system_idle std_srvs/srv/Trigger

# Get baseline summary
ros2 service call /get_baseline_summary std_srvs/srv/Trigger

# Save baseline
ros2 service call /save_baseline std_srvs/srv/Trigger
```

## Built-in Stress Scenarios

### 1. **pure_baseline** (3 minutes)
Pure system baseline measurement with zero artificial stress

### 2. **light_baseline** (2 minutes)
Minimal ROS 2 message load baseline (1Hz, 512-byte messages)

### 3. **high_throughput** (2 minutes)
Progressive message rate testing: 100Hz → 1kHz → 5kHz burst mode

### 4. **sensor_messages** (2 minutes)
Realistic sensor data: VGA images (30Hz) → 50k point clouds (10Hz) → laser scans (40Hz)

### 5. **large_payload** (2 minutes)
Payload size progression: 1KB strings → 100KB custom → 1MB custom structures

### 6. **dynamic_types** (2 minutes)
Automatic message type switching every 10 seconds

### 7. **cpu_stress** (2 minutes)
CPU load progression: 25% → 50% → 80% with message monitoring

### 8. **memory_stress** (1.5 minutes)
Memory allocation: 512MB → 2GB with message monitoring

### 9. **system_overload** (2 minutes)
Combined CPU + memory + message stress in three intensity phases

## Message Types Supported

### Basic Types
- **String**: Text messages with embedded timestamps
- **ByteMultiArray**: Raw binary data with structured headers
- **Twist**: Velocity commands with embedded sequence numbers

### Sensor Types
- **Image**: Realistic camera images (VGA/HD, RGB/RGBA/mono)
- **PointCloud2**: 3D point clouds with RGB data (configurable point counts)
- **LaserScan**: Lidar range/intensity data with realistic patterns

### Custom Types
- **Custom Large**: Structured binary payloads with embedded metadata fields

### Dynamic Features
- **Type Switching**: Automatically cycle through message types
- **Realistic Data**: Pre-generated sensor data with variations
- **Configurable Parameters**: Image resolution, point counts, scan ranges

## ROS 2 Topics

### Publishers
- `/stress_status` (String): System stress status in JSON format
- `/system_metrics` (String): System resource metrics
- `/scenario_status` (String): Orchestrator scenario status
- `/phase_progress` (String): Current scenario phase progress
- `/aggregated_metrics` (String): Collected metrics from all components
- `/performance_alerts` (String): Performance threshold alerts
- `/baseline_status` (String): Baseline measurement status
- `/baseline_metrics` (String): Baseline measurement data
- `/system_idle_status` (Bool): System idle validation status

### Subscribers
- `/stress_control` (String): Control commands for system stress
- `/orchestrator_commands` (String): Commands for stress components
- `/stress_test_metrics` (String): Metrics input for aggregation

### Services
- `/start_scenario` (String): Start a stress test scenario
- `/stop_scenario` (Trigger): Stop current scenario
- `/list_scenarios` (Trigger): List available scenarios
- `/get_orchestrator_status` (Trigger): Get orchestrator status
- `/start_baseline_measurement` (Trigger): Start baseline measurement
- `/stop_baseline_measurement` (Trigger): Stop baseline measurement
- `/validate_system_idle` (Trigger): Validate system idle state
- `/save_baseline` (Trigger): Save current baseline

## Configuration Parameters

### System Stress Parameters
- `cpu_intensity`: CPU stress intensity (0.0-1.0, default: 0.7)
- `memory_target_mb`: Memory allocation target in MB (default: 512)
- `auto_start`: Auto-start stress test (default: false)
- `duration_seconds`: Test duration, 0 for indefinite (default: 0)

### Message Stress Parameters
- `publish_rate`: Publishing rate in Hz (default: 10.0)
- `payload_size`: Message payload size in bytes (default: 1024)
- `message_type`: Message type (string/bytes/twist/image/pointcloud2/laserscan/custom_large)
- `burst_mode`: Enable burst mode (default: false)
- `dynamic_type_switching`: Enable automatic type switching (default: false)

### Baseline Parameters
- `measurement_duration`: Baseline measurement duration (default: 300.0s)
- `idle_detection_threshold`: CPU threshold for idle detection (default: 30.0%)
- `auto_validate_idle`: Validate idle before measurement (default: true)
- `stability_threshold`: Minimum stability score (default: 0.8)

### Sensor Message Parameters
- `image_width/height`: Image resolution (default: 640x480)
- `image_encoding`: Image encoding (rgb8/rgba8/mono8)
- `pointcloud_points`: Number of points in point cloud (default: 10000)
- `laserscan_ranges`: Number of laser scan ranges (default: 360)

## Advanced Features

### Metrics Collection
- **Real-time Aggregation**: Combine metrics from multiple sources
- **Statistical Analysis**: Percentiles, trends, regression analysis
- **Baseline Comparison**: Compare performance against baseline measurements
- **Alert System**: Configurable thresholds with automatic alerts
- **Export Options**: CSV/JSON export for external analysis

### Baseline Measurement
- **System Validation**: Ensure idle state before measurement
- **Quality Assessment**: Rate measurement quality and stability
- **Comprehensive Metrics**: CPU, memory, network, disk, load average
- **Comparison Engine**: Compare stress results against baseline
- **Persistent Storage**: Save/load baseline data across sessions

### Scenario Orchestration
- **Multi-Component Coordination**: Synchronize CPU, memory, and message stress
- **Phase Management**: Automatic transitions between scenario phases
- **Parameter Broadcasting**: Update multiple components simultaneously
- **Health Monitoring**: Monitor component status and handle failures
- **Timeline Control**: Precise timing and duration management

## Safety Features

- **Automatic Monitoring**: Continuous resource monitoring with safety thresholds
- **Critical Thresholds**: CPU 95%, Memory 95% (automatic shutdown)
- **Graceful Shutdown**: Proper cleanup on SIGINT/SIGTERM signals
- **Memory Protection**: Safety limits prevent system memory exhaustion
- **Process Management**: Robust process lifecycle management
- **Signal Handling**: Clean termination of all stress processes

## Performance Monitoring

### System Metrics
- CPU usage percentage and load average
- Memory usage, available memory, and allocation rates
- Network I/O rates (bytes sent/received per second)
- Disk I/O rates (read/write bytes per second)
- Process counts and context switch rates

### Message Metrics
- End-to-end latency measurement with percentiles
- Message throughput and loss rates
- Serialization/deserialization timing
- Queue overflow detection and recovery
- Duplicate and out-of-order message detection

### Analysis Features
- Trend detection and slope analysis
- Baseline comparison and deviation measurement
- Performance regression detection
- Statistical summary generation
- Time-series data retention and cleanup

## Examples

### Complete Stress Test Workflow
```bash
# 1. Start baseline measurement
ros2 run sys_stress_node baseline_collector &

# 2. Start metrics collection
ros2 run sys_stress_node metrics_collector &

# 3. Start orchestrator with auto-baseline
ros2 run sys_stress_node stress_orchestrator &

# 4. Run comprehensive stress scenario
ros2 service call /start_scenario std_msgs/srv/String "data: 'system_overload'"

# 5. Monitor progress
ros2 topic echo /phase_progress
```

### High-Frequency Message Testing
```bash
# Start subscriber
ros2 run sys_stress_node message_stress_subscriber &

# Start high-rate publisher
ros2 run sys_stress_node message_stress_publisher \
  --ros-args -p publish_rate:=1000.0 -p message_type:=bytes -p payload_size:=4096

# Monitor metrics
ros2 topic echo /aggregated_metrics
```

### Sensor Data Stress Testing
```bash
# Start components
ros2 run sys_stress_node message_stress_subscriber &
ros2 run sys_stress_node metrics_collector &

# Test realistic sensor messages
ros2 service call /start_scenario std_msgs/srv/String "data: 'sensor_messages'"
```

### Baseline-Only Measurement
```bash
# Pure system baseline (no ROS 2 message load)
ros2 service call /start_scenario std_msgs/srv/String "data: 'pure_baseline'"

# View baseline results
ros2 service call /get_baseline_summary std_srvs/srv/Trigger
```

## Troubleshooting

### Common Issues

1. **High CPU/Memory Usage**: Check safety thresholds and adjust intensity
2. **Message Loss**: Reduce publishing rate or increase QoS queue depth
3. **Baseline Quality Poor**: Ensure system is idle and increase measurement duration
4. **Process Cleanup Issues**: Use Ctrl+C for graceful shutdown, avoid SIGKILL

### Performance Tuning

1. **CPU Stress**: Adjust process count and intensity based on system capabilities
2. **Message Stress**: Tune QoS settings, payload sizes, and publishing rates
3. **Baseline**: Increase measurement duration for better statistical significance
4. **Monitoring**: Adjust collection intervals based on system load

## Contributing

When adding new features:
1. Follow existing code patterns and naming conventions
2. Add comprehensive error handling and logging
3. Update parameter documentation and examples
4. Test both standalone and ROS 2 modes
5. Update this README with new functionality

## License

MIT License