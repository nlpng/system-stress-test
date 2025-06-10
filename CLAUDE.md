# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
We're building a simple ROS (Robotic Operating System) 2 humble node to stress test the CPUs and memory by increasing the load of both. This solution assumes that the CPU and memory load from all other background processes are negligible.

## Architecture

### Core Components:
- **Package Name**: sys_stress_node
- **Language**: Python
- **ROS Framework**: ROS 2 humble 
- **Build System**: colcon
- **Structure**: Standard ROS 2 Python package with node implementation, publishers, subscribers, and timers

## Common Development Commands

### Building
```bash
colcon build --packages-select sys_stress_node
```

### Running
```bash
# Source the workspace
source install/setup.bash

# Run the node directly
ros2 run sys_stress_node stress_node

# Run with launch file (if available)
ros2 launch sys_stress_node stress_test.launch.py
```

### Testing
```bash
# Run tests for the package
colcon test --packages-select sys_stress_node

# View test results
colcon test-result --verbose
```

### 🔄 Project Awareness & Context
- **Always read `CLAUDE.md`** at the start of a new conversation to understand the project's architecture, goals, style, and constraints.
- **Check `TASK.md`** before starting a new task. If the task isn’t listed, add it with a brief description and today's date.
- **Use consistent naming conventions, file structure, and architecture patterns** as described in this `CLAUDE.md`.

### 🧱 Code Structure & Modularity
- **Never create a file longer than 500 lines of code.** If a file approaches this limit, refactor by splitting it into modules or helper files.
- **Organize code into clearly separated modules**, grouped by feature or responsibility.

### ✅ Task Completion
- **Mark completed tasks in `TASK.md`** immediately after finishing them.
- Add new sub-tasks or TODOs discovered during development to `TASK.md` under a “Discovered During Work” section.
- Commit the changes using short and concise message once finished single task.

### 📚 Documentation & Explainability
- **Update `README.md`** when new features are added, dependencies change, or setup steps are modified.
- **Comment non-obvious code** and ensure everything is understandable to a mid-level developer.
- When writing complex logic, **add an inline comment** explaining the why, not just the what.

### 🧠 AI Behavior Rules
- **Never assume missing context. Ask questions if uncertain.**
- **Never hallucinate libraries or functions** – only use known, verified packages and libraries.
- **Always confirm file paths and module names** exist before referencing them in code.
- **Never delete or overwrite existing code** unless explicitly instructed to or if part of a task from `TASK.md`.
