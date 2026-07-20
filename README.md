# MARK — Multi-Agent Research Kit

MARK is a local-first, multi-agent research system that runs entirely on your machine. It uses a supervisor-worker architecture where a planner breaks down tasks and delegates to specialized workers (code, docs, research, etc.) that execute in parallel.

## Quick Start

```bash
# Clone and enter
git clone https://github.com/your-org/mark.git
cd mark

# Install dependencies (requires Python 3.11+)
pip install -e .

# Run a task
mark "research the latest developments in quantum computing"
```

## Usage

### Basic Commands

```bash
# Run a single task and exit
mark "your task description here"

# Run with verbose logging
mark -v "debug this issue"

# Run with a specific model (if configured)
mark --model gpt-4 "complex reasoning task"

# List available workers
mark --list-workers

# Show version
mark --version
```

### Task Examples

```bash
# Code generation
mark "create a Python CLI tool for parsing JSON logs"

# Research
mark "summarize the key findings from the latest Transformer paper"

# Documentation
mark "write API docs for the auth module in workspace/api"

# Debugging
mark "find and fix the memory leak in the data processor"
```

### Configuration

Create a `.markrc` file in your project root or home directory:

```yaml
# .markrc
model: gpt-4
max_workers: 4
timeout: 300
workspace: ./workspace
log_level: INFO
```

Environment variables also work:
```bash
export MARK_MODEL=gpt-4
export MARK_MAX_WORKERS=4
export MARK_WORKSPACE=./workspace
```

## Shutdown Procedures

### Graceful Shutdown (Recommended)

Press `Ctrl+C` once to initiate graceful shutdown:
- Supervisor stops accepting new tasks
- Active workers finish their current subtask
- Results are saved to workspace
- Clean exit with summary

```bash
$ mark "long research task"
^C
[INFO] Shutdown signal received, finishing active work...
[INFO] Worker(code) completed: generated parser.py
[INFO] Worker(research) completed: saved findings.md
[INFO] All workers stopped. Results in ./workspace/output/
```

### Force Shutdown (Emergency)

Press `Ctrl+C` twice within 2 seconds to force immediate termination:
- All workers killed immediately
- Partial results may be lost
- Use only if graceful shutdown hangs