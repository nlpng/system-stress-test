from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'sys_stress_node'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='System Stress Test Maintainer',
    maintainer_email='user@example.com',
    description='ROS 2 node for system stress testing of CPU and memory',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'stress_node = sys_stress_node.stress_node:main',
            'message_stress_publisher = sys_stress_node.message_stress_publisher:main',
            'message_stress_subscriber = sys_stress_node.message_stress_subscriber:main',
            'metrics_collector = sys_stress_node.metrics_collector:main',
            'stress_orchestrator = sys_stress_node.stress_orchestrator:main',
            'baseline_collector = sys_stress_node.baseline_collector:main',
        ],
    },
)