#!/usr/bin/env python3

import paramiko
import time
import socket


USER = 'nao'
PASS = 'nao'

CLIENT = '~/scripts/pepper_camera_service.py'
REMOTE_PYTHONPATH = ':'.join([
    '/opt/aldebaran/lib/python2.7/site-packages',
    '/usr/lib/python27.zip',
    '/usr/lib/python2.7',
    '/usr/lib/python2.7/plat-linux2',
    '/usr/lib/python2.7/lib-tk',
    '/usr/lib/python2.7/lib-old',
    '/usr/lib/python2.7/lib-dynload',
    '/usr/lib/python2.7/site-packages',
])
PYTHONPATH_EXPORT = 'PYTHONPATH="{paths}"${{PYTHONPATH:+:$PYTHONPATH}}'.format(paths=REMOTE_PYTHONPATH)


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
    script = "~/scripts/pepper_camera_service.py --host {}".format(local_ip)
    command = "export {py_env} && nohup python2 {script} &".format(py_env=PYTHONPATH_EXPORT, script=script)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=USER, password=PASS)
    ssh.exec_command(command)
    time.sleep(0.2)
    ssh.close()

if __name__ == "__main__":
    deploy_remote()
