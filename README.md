# ROS 2 System Stress Test Node

A ROS 2 humble package for stress testing system CPU and memory resources with real-time monitoring and safety features.

## Overview

This package provides a comprehensive system stress testing solution that can:
- Stress test CPU with configurable intensity
- Stress test memory with configurable allocation targets
- Monitor system resources in real-time
- Automatically stop tests when safety thresholds are exceeded
- Publish metrics and status via ROS 2 topics
- **Run standalone without ROS 2** for simple stress testing needs

## Package Structure

```
sys_stress_node/
├── package.xml                 # Package metadata and dependencies
├── setup.py                   # Python package setup
├── setup.cfg                  # Package configuration
├── resource/                  # Package resource marker
├── sys_stress_node/           # Python package
│   ├── __init__.py
│   ├── cpu_stress.py         # CPU stress testing module
│   ├── memory_stress.py      # Memory stress testing module
│   ├── system_monitor.py     # System monitoring module
│   └── stress_node.py        # Main ROS 2 node
├── launch/                   # Launch files
│   └── stress_test.launch.py
└── config/                   # Configuration files
    └── default_params.yaml
```

## Dependencies

### For ROS 2 Usage:
- ROS 2 humble
- rclpy
- std_msgs
- sensor_msgs
- python3-psutil

### For Standalone Usage:
- Python 3.6+
- python3-psutil (install with: `pip3 install psutil`)

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
pip3 install psutil

# No build required - run modules directly
```

## Usage

### Standalone Usage (Without ROS 2)

The stress testing modules can be run independently without ROS 2:

#### CPU Stress Testing
```bash
# Basic CPU stress test
python3 src/sys_stress_node/sys_stress_node/cpu_stress.py

# Custom intensity and duration
python3 src/sys_stress_node/sys_stress_node/cpu_stress.py --intensity 0.5 --duration 30

# Verbose output with custom thread count
python3 src/sys_stress_node/sys_stress_node/cpu_stress.py -i 0.8 -t 4 -v
```

#### Memory Stress Testing
```bash
# Basic memory stress test
python3 src/sys_stress_node/sys_stress_node/memory_stress.py

# Custom target and duration
python3 src/sys_stress_node/sys_stress_node/memory_stress.py --target 1024 --duration 60

# Verbose output with system info
python3 src/sys_stress_node/sys_stress_node/memory_stress.py -t 512 -v -s

# Show help and all available options
python3 src/sys_stress_node/sys_stress_node/cpu_stress.py --help
python3 src/sys_stress_node/sys_stress_node/memory_stress.py --help
```

#### Standalone Command Options

**CPU Stress Options:**
- `--intensity, -i`: CPU stress intensity (0.0 to 1.0, default: 0.8)
- `--duration, -d`: Duration in seconds (default: indefinite)
- `--threads, -t`: Number of threads (default: CPU count)
- `--verbose, -v`: Verbose output with status updates

**Memory Stress Options:**
- `--target, -t`: Target memory allocation in MB (default: 512)
- `--duration, -d`: Duration in seconds (default: indefinite)
- `--chunk-size, -c`: Allocation chunk size in MB (default: 10)
- `--verbose, -v`: Verbose output with status updates
- `--show-system-info, -s`: Show system memory information

### ROS 2 Usage

#### Basic Usage

```bash
# Run with default parameters
ros2 run sys_stress_node stress_node

# Run with launch file
ros2 launch sys_stress_node stress_test.launch.py

# Run with custom parameters
ros2 launch sys_stress_node stress_test.launch.py cpu_intensity:=0.8 memory_target_mb:=1024
```

### Launch Parameters

- `cpu_intensity`: CPU stress intensity (0.0 to 1.0, default: 0.7)
- `memory_target_mb`: Memory allocation target in MB (default: 512)
- `auto_start`: Auto-start stress test on node startup (default: false)
- `duration_seconds`: Test duration in seconds, 0 for indefinite (default: 0)
- `enable_safety_monitoring`: Enable safety monitoring (default: true)
- `publish_rate_hz`: Status publishing rate (default: 1.0)

### ROS 2 Topics

#### Publishers
- `/stress_status` (String): Detailed status in JSON format
- `/system_metrics` (String): System metrics in JSON format
- `/cpu_load` (Float32): Current CPU usage percentage
- `/memory_usage` (Float32): Current memory usage percentage

#### Subscribers
- `/stress_control` (String): Control commands ("start", "stop", "restart")
- `/cpu_intensity_control` (Float32): Adjust CPU intensity (0.0-1.0)
- `/memory_target_control` (Float32): Adjust memory target (MB)

### Control Commands

```bash
# Start stress test
ros2 topic pub /stress_control std_msgs/String "data: 'start'" --once

# Stop stress test
ros2 topic pub /stress_control std_msgs/String "data: 'stop'" --once

# Adjust CPU intensity
ros2 topic pub /cpu_intensity_control std_msgs/Float32 "data: 0.5" --once

# Adjust memory target
ros2 topic pub /memory_target_control std_msgs/Float32 "data: 256.0" --once
```

### Monitoring

```bash
# Monitor status
ros2 topic echo /stress_status

# Monitor system metrics
ros2 topic echo /system_metrics

# Monitor CPU load
ros2 topic echo /cpu_load

# Monitor memory usage
ros2 topic echo /memory_usage
```

## Safety Features

- Automatic safety monitoring with configurable thresholds
- CPU critical threshold: 95% (automatic shutdown)
- Memory critical threshold: 95% (automatic shutdown)
- Graceful shutdown on SIGINT/SIGTERM signals
- Memory allocation safety limits (max 80% of available memory)

## Configuration

The package includes a default configuration file at `config/default_params.yaml`. You can override parameters using:

```bash
ros2 run sys_stress_node stress_node --ros-args --params-file /path/to/your/config.yaml
```

## Examples

### High Intensity Test
```bash
ros2 launch sys_stress_node stress_test.launch.py \
  cpu_intensity:=0.9 \
  memory_target_mb:=2048 \
  auto_start:=true \
  duration_seconds:=60
```

### Monitoring Only
```bash
ros2 launch sys_stress_node stress_test.launch.py \
  cpu_intensity:=0.0 \
  memory_target_mb:=0 \
  enable_safety_monitoring:=true
```

## License

MIT License