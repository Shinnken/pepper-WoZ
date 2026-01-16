#!/usr/bin/env python3

import paramiko
import time
import socket


USER = 'nao'
PASS = 'nao'

CLIENT = '~/scripts/pepper_camera_service.py'
# Updated for Python 3.9 on NAO
REMOTE_PYTHONPATH = ':'.join([
    '/home/nao/.local/share/PackageManager/apps/python3nao/lib/python3.9/site-packages',
])

# Define the required library preload
LD_PRELOAD_PATH = '/home/nao/.local/share/PackageManager/apps/python3nao/bin/libcrypt.so.1'

# Define the virtual environment Python path
VENV_PYTHON = "/home/nao/.venv/bin/python3"

# Export both variables for your remote environment
PYTHON_ENV_EXPORT = (
    'export LD_PRELOAD="{lib}":$LD_PRELOAD && '
    'export PYTHONPATH="{paths}"${{PYTHONPATH:+:$PYTHONPATH}}'
).format(lib=LD_PRELOAD_PATH, paths=REMOTE_PYTHONPATH)


def get_local_ip() -> str:
	"""Return the IP address associated with the default outbound interface."""
	with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
		try:
			s.connect(("8.8.8.8", 80))
			return s.getsockname()[0]
		except OSError:
			return "127.0.0.1"


def deploy_remote(host='192.168.1.102'):
    local_ip = get_local_ip()
    script = "~/scripts/pepper_camera_service.py --host {} --no_life".format(local_ip)
    command = "export {py_env} && nohup {venv_py} {script} &".format(
        py_env=PYTHON_ENV_EXPORT, 
        venv_py=VENV_PYTHON,
        script=script
    )
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=USER, password=PASS)
    ssh.exec_command(command)
    time.sleep(0.2)
    ssh.close()

if __name__ == "__main__":
    deploy_remote()
