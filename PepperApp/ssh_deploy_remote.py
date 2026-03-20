#!/usr/bin/env python3

import paramiko
import time
import socket
import os


USER = 'nao'
PASS = 'nao'

CLIENT = '~/scripts/pepper_camera_service.py'
# Updated for Python 3.9 on NAO
REMOTE_PYTHONPATH = ':'.join([
    '/data/home/nao/.local/share/PackageManager/apps/python3nao/lib/python3.9/site-packages',
])

# Define the required library preload
LD_PRELOAD_PATH = '/home/nao/.local/share/PackageManager/apps/python3nao/bin/libcrypt.so.1'

# Define the virtual environment Python path
VENV_PYTHON = os.getenv("PEPPER_REMOTE_PYTHON", "/home/nao/apps/python3nao/bin/python3")

# Export both variables for your remote environment
PYTHON_ENV_EXPORT = (
    'export LD_PRELOAD="{lib}":$LD_PRELOAD && '
    'export PYTHONPATH="{paths}"${{PYTHONPATH:+:$PYTHONPATH}}'
).format(lib=LD_PRELOAD_PATH, paths=REMOTE_PYTHONPATH)


def get_local_ip(target_host: str = "8.8.8.8") -> str:
    """Return the IP address associated with the route to target_host."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect((target_host, 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def deploy_remote(host='nao.local'):
    local_ip = get_local_ip(host)
    script = "~/scripts/pepper_camera_service.py --host {}".format(local_ip)
    command = "export {py_env} && nohup {venv_py} {script} &".format(
        py_env=PYTHON_ENV_EXPORT, 
        venv_py=VENV_PYTHON,
        script=script
    )
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=USER, password=PASS)
    ssh.exec_command(command)
    startup_delay_sec = float(os.getenv("PEPPER_REMOTE_START_DELAY_SEC", "0.2"))
    time.sleep(startup_delay_sec)
    ssh.close()

if __name__ == "__main__":
    deploy_remote()
