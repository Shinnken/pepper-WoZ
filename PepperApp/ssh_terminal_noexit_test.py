import paramiko
import time

pepper_python_path = "/opt/aldebaran/lib/python2.7/site-packages"
COMMAND_TO_RUN = f"nohup env PYTHONPATH={pepper_python_path} python2 ~/led_test.py &"

# Create an SSH client instance
client = paramiko.SSHClient()

client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    print(f"Connecting...")
    # Connect to the remote server
    client.connect(
        hostname="192.168.1.110",
        username="nao",
        password="nao",
        timeout=10  # Add a timeout for the connection
    )

    print("Connection successful.")
    print(f"Executing command: {COMMAND_TO_RUN}")

    # Execute the command
    client.exec_command(COMMAND_TO_RUN)

    # Note: We don't need to wait for the command to finish because it's running
    # in the background. We can give it a second to ensure it started.
    time.sleep(1)


except Exception as e:
    print(f"An error occurred: {e}")

finally:
    # This block will always run, ensuring the connection is closed.
    print("Closing SSH connection.")
    client.close()
    print("Connection closed. The remote script should still be running.")