from flask import Flask, request, jsonify
import yaml
import os
from typing import Dict, List
import atexit
import threading
from queue import Queue
import subprocess
import asyncio
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

# 全局配置
MAX_MYSQL_INSTANCES = 5  # 最大MySQL实例数
DOCKER_COMPOSE_DIR = "docker_compose_files"  # 存储docker-compose文件的目录
BASE_MYSQL_PORT = 3306  # MySQL基础端口号

# 添加新的状态常量
INSTANCE_STATUS = {
    'STARTING': 'starting',
    'RUNNING': 'running',
    'FAILED': 'failed',
    'STOPPED': 'stopped'
}

# 全局状态
running_instances: Dict[int, dict] = {}  # 端口号 -> 实例信息的映射
waiting_queue = Queue()  # 等待队列
port_lock = threading.Lock()  # 端口分配锁
executor = ThreadPoolExecutor(max_workers=3)  # 用于异步执行docker-compose命令

# 确保docker-compose文件目录存在
os.makedirs(DOCKER_COMPOSE_DIR, exist_ok=True)

def get_next_available_port() -> int:
    """获取下一个可用的端口号"""
    with port_lock:
        port = BASE_MYSQL_PORT
        while port in running_instances:
            port += 1
        return port

def generate_docker_compose(port: int, mysql_root_password: str) -> str:
    """生成docker-compose.yml文件内容"""
    compose_config = {
        'version': '3',
        'services': {
            f'mysql_{port}': {
                'image': 'mysql:5.7',
                'ports': [f'{port}:3306'],
                'environment': {
                    'MYSQL_ROOT_PASSWORD': mysql_root_password
                },
                'volumes': [f'mysql_data_{port}:/var/lib/mysql']
            }
        },
        'volumes': {
            f'mysql_data_{port}': {}
        }
    }
    return yaml.dump(compose_config)

def write_docker_compose(port: int, content: str) -> str:
    """将docker-compose内容写入文件"""
    filename = os.path.join(DOCKER_COMPOSE_DIR, f'docker-compose_{port}.yml')
    with open(filename, 'w') as f:
        f.write(content)
    return filename

def async_start_mysql(port: int, compose_file: str, project_name: str):
    """异步启动MySQL实例"""
    try:
        # 使用subprocess替代os.system，这样可以获取更多控制和输出信息
        process = subprocess.run(
            f'docker-compose -f {compose_file} -p {project_name} up -d',
            shell=True,
            capture_output=True,
            text=True
        )
        
        if process.returncode == 0:
            running_instances[port]['status'] = INSTANCE_STATUS['RUNNING']
            running_instances[port]['error'] = None
        else:
            running_instances[port]['status'] = INSTANCE_STATUS['FAILED']
            running_instances[port]['error'] = process.stderr
    except Exception as e:
        running_instances[port]['status'] = INSTANCE_STATUS['FAILED']
        running_instances[port]['error'] = str(e)

def start_mysql_instance(port: int, mysql_root_password: str) -> dict:
    """启动MySQL实例"""
    compose_content = generate_docker_compose(port, mysql_root_password)
    compose_file = write_docker_compose(port, compose_content)
    
    project_name = f'mysql_{port}'
    
    instance_info = {
        'port': port,
        'host': 'localhost',
        'username': 'root',
        'password': mysql_root_password,
        'compose_file': compose_file,
        'project_name': project_name,
        'status': INSTANCE_STATUS['STARTING'],
        'error': None
    }
    
    running_instances[port] = instance_info
    
    # 异步启动MySQL实例
    executor.submit(async_start_mysql, port, compose_file, project_name)
    
    return instance_info

def stop_mysql_instance(port: int):
    """停止MySQL实例"""
    if port not in running_instances:
        return
    
    instance_info = running_instances[port]
    compose_file = instance_info['compose_file']
    project_name = instance_info['project_name']
    
    # 停止并删除容器
    os.system(f'docker-compose -f {compose_file} -p {project_name} down -v')
    
    # 删除docker-compose文件
    if os.path.exists(compose_file):
        os.remove(compose_file)
    
    del running_instances[port]

def process_waiting_queue():
    """处理等待队列"""
    while not waiting_queue.empty() and len(running_instances) < MAX_MYSQL_INSTANCES:
        mysql_config = waiting_queue.get()
        port = get_next_available_port()
        start_mysql_instance(port, mysql_config['mysql_root_password'])

@app.route('/mysql/start', methods=['POST'])
def start_mysql():
    """启动MySQL服务的API端点"""
    data = request.get_json()
    mysql_root_password = data.get('mysql_root_password', 'root')
    
    if len(running_instances) >= MAX_MYSQL_INSTANCES:
        waiting_queue.put({'mysql_root_password': mysql_root_password})
        return jsonify({
            'status': 'queued',
            'message': 'Maximum number of MySQL instances reached. Request queued.'
        }), 202
    
    port = get_next_available_port()
    instance_info = start_mysql_instance(port, mysql_root_password)
    
    return jsonify({
        'status': 'accepted',
        'message': 'MySQL instance is starting',
        'data': instance_info
    }), 202

@app.route('/mysql/stop/<int:port>', methods=['POST'])
def stop_mysql(port):
    """停止MySQL服务的API端点"""
    if port not in running_instances:
        return jsonify({
            'status': 'error',
            'message': f'No MySQL instance running on port {port}'
        }), 404
    
    stop_mysql_instance(port)
    process_waiting_queue()  # 处理等待队列中的请求
    
    return jsonify({
        'status': 'success',
        'message': f'MySQL instance on port {port} stopped successfully'
    })

@app.route('/mysql/list', methods=['GET'])
def list_mysql():
    """列出所有运行中的MySQL实例"""
    return jsonify({
        'status': 'success',
        'data': {
            'running_instances': list(running_instances.values()),
            'waiting_queue_size': waiting_queue.qsize()
        }
    })

@app.route('/mysql/status/<int:port>', methods=['GET'])
def get_mysql_status(port):
    """获取MySQL实例状态的API端点"""
    if port not in running_instances:
        return jsonify({
            'status': 'error',
            'message': f'No MySQL instance found on port {port}'
        }), 404
    
    instance_info = running_instances[port]
    return jsonify({
        'status': 'success',
        'data': {
            'port': port,
            'status': instance_info['status'],
            'error': instance_info['error']
        }
    })

def cleanup():
    """清理所有运行的MySQL实例"""
    for port in list(running_instances.keys()):
        stop_mysql_instance(port)

# 注册清理函数
atexit.register(cleanup)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5600)
