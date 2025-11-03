#!./venv/bin/python3
from pepper_app_socket_manager import SocketManager
from pepper_app_ui import App
# from pepper_app_ssh_manager import SSHManager
if __name__ == "__main__":

    HOST = "0.0.0.0"
    PORT_TCP = 54321
    PORT_UDP = 54322

    socket_manager = None
    try:
        # ssh_manager = SSHManager("nao", "nao")
        socket_manager = SocketManager(HOST, PORT_TCP, PORT_UDP)
    except KeyboardInterrupt as e:
        print(f"Error: {e}")
        if socket_manager is not None:
                socket_manager.exit()
    except OSError as e:
        print(f"OS Error: {e}")
        if socket_manager is not None:
                socket_manager.exit()
        


    app = App(socket_manager)
    app.mainloop()

    