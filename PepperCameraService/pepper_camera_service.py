import argparse
from pepper_camera import PepperCamera
from pepper_socket_manager import PepperSocketManager



if __name__ == "__main__":
    print("Starting Pepper Camera Client")
    parser = argparse.ArgumentParser(description='Pepper Camera Client')
    parser.add_argument('--host', type=str, default="192.168.1.103", help='Host IP address')
    parser.add_argument('--port_tcp', type=int, default=54321, help='Port number')
    parser.add_argument('--port_udp', type=int, default=54322, help='Port number')
    args = parser.parse_args()
    pepper_socket_manager = None
    try:
        print("Connecting to Pepper Camera...")
        pepper_camera = PepperCamera()
        print("Connecting to Pepper Socket...")
        pepper_socket_manager = PepperSocketManager(args.host, args.port_tcp, args.port_udp, pepper_camera)
    except Exception as e:
        print("Error:", e)
        if pepper_socket_manager:
            pepper_socket_manager.exit()
            pepper_socket_manager.tcp_thread.join()
            pepper_socket_manager.udp_thread.join()

