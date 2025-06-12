#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, TextSubstitution, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
import os


def generate_launch_description():
    """Generate launch description for stress test node"""
    
    # Declare launch arguments
    cpu_intensity_arg = DeclareLaunchArgument(
        'cpu_intensity',
        default_value='0.7',
        description='CPU stress intensity (0.0 to 1.0)'
    )
    
    memory_target_arg = DeclareLaunchArgument(
        'memory_target_mb',
        default_value='512',
        description='Memory allocation target in MB'
    )
    
    auto_start_arg = DeclareLaunchArgument(
        'auto_start',
        default_value='false',
        description='Auto-start stress test on node startup'
    )
    
    duration_arg = DeclareLaunchArgument(
        'duration_seconds',
        default_value='0',
        description='Stress test duration in seconds (0 = indefinite)'
    )
    
    enable_safety_arg = DeclareLaunchArgument(
        'enable_safety_monitoring',
        default_value='true',
        description='Enable safety monitoring with automatic shutdown'
    )
    
    publish_rate_arg = DeclareLaunchArgument(
        'publish_rate_hz',
        default_value='1.0',
        description='Rate for publishing status updates (Hz)'
    )
    
    node_name_arg = DeclareLaunchArgument(
        'node_name',
        default_value='stress_test_node',
        description='Name of the stress test node'
    )
    
    namespace_arg = DeclareLaunchArgument(
        'namespace',
        default_value='',
        description='ROS namespace for the node'
    )
    
    # Throughput testing arguments
    enable_throughput_testing_arg = DeclareLaunchArgument(
        'enable_throughput_testing',
        default_value='false',
        description='Enable throughput testing components'
    )
    
    throughput_scenario_arg = DeclareLaunchArgument(
        'throughput_scenario',
        default_value='throughput_progression',
        description='Throughput test scenario to run'
    )
    
    config_file_arg = DeclareLaunchArgument(
        'config_file',
        default_value='',
        description='Path to configuration YAML file'
    )
    
    # Create stress test node
    stress_test_node = Node(
        package='sys_stress_node',
        executable='stress_node',
        name=LaunchConfiguration('node_name'),
        namespace=LaunchConfiguration('namespace'),
        parameters=[
            {
                'cpu_intensity': LaunchConfiguration('cpu_intensity'),
                'memory_target_mb': LaunchConfiguration('memory_target_mb'),
                'auto_start': LaunchConfiguration('auto_start'),
                'duration_seconds': LaunchConfiguration('duration_seconds'),
                'enable_safety_monitoring': LaunchConfiguration('enable_safety_monitoring'),
                'publish_rate_hz': LaunchConfiguration('publish_rate_hz'),
            }
        ],
        output='screen',
        emulate_tty=True,
    )
    
    # Throughput tester node (conditionally launched)
    throughput_tester_node = Node(
        package='sys_stress_node',
        executable='throughput_tester',
        name='throughput_tester',
        namespace=LaunchConfiguration('namespace'),
        parameters=[
            PathJoinSubstitution([
                FindPackageShare('sys_stress_node'),
                'config',
                'throughput_test_params.yaml'
            ])
        ],
        output='screen',
        emulate_tty=True,
        condition=IfCondition(LaunchConfiguration('enable_throughput_testing'))
    )
    
    # Stress orchestrator node (conditionally launched)
    stress_orchestrator_node = Node(
        package='sys_stress_node',
        executable='stress_orchestrator',
        name='stress_orchestrator',
        namespace=LaunchConfiguration('namespace'),
        parameters=[
            {
                'auto_start': LaunchConfiguration('auto_start'),
                'default_scenario': LaunchConfiguration('throughput_scenario'),
            },
            PathJoinSubstitution([
                FindPackageShare('sys_stress_node'),
                'config',
                'throughput_test_params.yaml'
            ])
        ],
        output='screen',
        emulate_tty=True,
        condition=IfCondition(LaunchConfiguration('enable_throughput_testing'))
    )
    
    # Log launch configuration
    launch_info = LogInfo(
        msg=[
            'Starting stress test node with configuration:\n',
            '  CPU Intensity: ', LaunchConfiguration('cpu_intensity'), '\n',
            '  Memory Target: ', LaunchConfiguration('memory_target_mb'), ' MB\n',
            '  Auto Start: ', LaunchConfiguration('auto_start'), '\n',
            '  Duration: ', LaunchConfiguration('duration_seconds'), ' seconds\n',
            '  Safety Monitoring: ', LaunchConfiguration('enable_safety_monitoring'), '\n',
            '  Publish Rate: ', LaunchConfiguration('publish_rate_hz'), ' Hz\n',
            '  Node Name: ', LaunchConfiguration('node_name'), '\n',
            '  Namespace: ', LaunchConfiguration('namespace'), '\n',
            '  Throughput Testing: ', LaunchConfiguration('enable_throughput_testing'), '\n',
            '  Throughput Scenario: ', LaunchConfiguration('throughput_scenario')
        ]
    )
    
    return LaunchDescription([
        cpu_intensity_arg,
        memory_target_arg,
        auto_start_arg,
        duration_arg,
        enable_safety_arg,
        publish_rate_arg,
        node_name_arg,
        namespace_arg,
        enable_throughput_testing_arg,
        throughput_scenario_arg,
        config_file_arg,
        launch_info,
        stress_test_node,
        throughput_tester_node,
        stress_orchestrator_node,
    ])