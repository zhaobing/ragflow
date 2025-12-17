#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Function to load environment variables from .env file
load_env_file() {
    # Get the directory of the current script
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local env_file="$script_dir/.env"

    # Check if .env file exists
    if [ -f "$env_file" ]; then
        echo "Loading environment variables from: $env_file"
        # Source the .env file
        set -a
        source "$env_file" 
        set +a
    else
        echo "Warning: .env file not found at: $env_file"
    fi
}

# Load environment variables
load_env_file

# Unset HTTP proxies that might be set by Docker daemon
export http_proxy=""; export https_proxy=""; export no_proxy=""; export HTTP_PROXY=""; export HTTPS_PROXY=""; export NO_PROXY=""
export PYTHONPATH=$(pwd)

export LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/
JEMALLOC_PATH=$(pkg-config --variable=libdir jemalloc)/libjemalloc.so

PY=python3

# Set default number of workers if WS is not set or less than 1
if [[ -z "$WS" || $WS -lt 1 ]]; then
  WS=1
fi

# Maximum number of retries for each task executor and server
MAX_RETRIES=5

# Flag to control termination
STOP=false

# Array to keep track of child PIDs
PIDS=()

# Set the path to the NLTK data directory
export NLTK_DATA="./nltk_data"

# Function to handle termination signals
cleanup() {
  echo "Termination signal received. Shutting down..."
  STOP=true
  # Terminate all child processes
  for pid in "${PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      echo "Killing process $pid"
      kill "$pid"
    fi
  done
  exit 0
}

# Trap SIGINT and SIGTERM to invoke cleanup
trap cleanup SIGINT SIGTERM

# Function to check if port is available
check_port_available() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 1  # Port is occupied
    else
        return 0  # Port is available
    fi
}

# Function to find next available port starting from base
find_available_port() {
    local base_port=$1
    local port=$base_port
    while [ $port -lt 65535 ]; do
        if check_port_available $port; then
            echo $port
            return 0
        fi
        port=$((port + 1))
    done
    echo "No available port found starting from $base_port" >&2
    return 1
}

# Function to execute task_executor with debug mode
task_exe_debug(){
    local task_id=$1
    local base_port=$((9100 + task_id * 10))  # 每个task使用不同端口，从9100开始，间隔10
    local debug_port=$(find_available_port $base_port)
    local retry_count=0
    echo "Using debug port $debug_port for task $task_id"
    while ! $STOP && [ $retry_count -lt $MAX_RETRIES ]; do
        echo "Starting task_executor.py for task $task_id in debug mode on port $debug_port (Attempt $((retry_count+1)))"
        LD_PRELOAD=$JEMALLOC_PATH $PY -m debugpy --listen $debug_port --wait-for-client rag/svr/task_executor.py "$task_id"
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 0 ]; then
            echo "task_executor.py for task $task_id exited successfully."
            break
        else
            echo "task_executor.py for task $task_id failed with exit code $EXIT_CODE. Retrying..." >&2
            retry_count=$((retry_count + 1))
            sleep 2
        fi
    done

    if [ $retry_count -ge $MAX_RETRIES ]; then
        echo "task_executor.py for task $task_id failed after $MAX_RETRIES attempts. Exiting..." >&2
        cleanup
    fi
}

# Function to execute ragflow_server with debug mode
run_server_debug(){
    local debug_port=$(find_available_port 9090)  # API服务器使用9090开始
    local retry_count=0
    echo "Using debug port $debug_port for API server"
    while ! $STOP && [ $retry_count -lt $MAX_RETRIES ]; do
        echo "Starting ragflow_server.py in debug mode on port $debug_port (Attempt $((retry_count+1)))"
        $PY -m debugpy --listen $debug_port --wait-for-client api/ragflow_server.py
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 0 ]; then
            echo "ragflow_server.py exited successfully."
            break
        else
            echo "ragflow_server.py failed with exit code $EXIT_CODE. Retrying..." >&2
            retry_count=$((retry_count + 1))
            sleep 2
        fi
    done

    if [ $retry_count -ge $MAX_RETRIES ]; then
        echo "ragflow_server.py failed after $MAX_RETRIES attempts. Exiting..." >&2
        cleanup
    fi
}

# 询问用户要调试什么
echo "请选择调试模式:"
echo "1. 只调试 API 服务器 (ragflow_server.py)"
echo "2. 只调试任务执行器 (task_executor.py)"  
echo "3. 同时调试 API 服务器和任务执行器"
echo "4. 正常启动模式（无调试）"

read -p "请输入选择 (1-4): " choice

case $choice in
    1)
        echo "启动 API 服务器调试模式..."
        run_server_debug &
        PIDS+=($!)
        ;;
    2)
        echo "启动任务执行器调试模式..."
        for ((i=0;i<WS;i++))
        do
          task_exe_debug "$i" &
          PIDS+=($!)
        done
        ;;
    3)
        echo "启动完整调试模式..."
        run_server_debug &
        PIDS+=($!)
        for ((i=0;i<WS;i++))
        do
          task_exe_debug "$i" &
          PIDS+=($!)
        done
        ;;
    4)
        echo "正常启动模式..."
        # 启动原始的非调试版本
        for ((i=0;i<WS;i++))
        do
          LD_PRELOAD=$JEMALLOC_PATH $PY rag/svr/task_executor.py "$i" &
          PIDS+=($!)
        done
        $PY api/ragflow_server.py &
        PIDS+=($!)
        ;;
    *)
        echo "无效选择，退出"
        exit 1
        ;;
esac

# Wait for all background processes to finish
wait
