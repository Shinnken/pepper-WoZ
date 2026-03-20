import argparse
import asyncio

from pepper_camera import PepperCamera
from pepper_socket_manager import PepperSocketManager


async def main() -> None:
    print("Starting Pepper Camera Client")
    parser = argparse.ArgumentParser(description="Pepper Camera Client")
    parser.add_argument("--host", type=str, default="192.168.1.103", help="Host IP address")
    parser.add_argument("--port_tcp", type=int, default=54321, help="Port number")
    parser.add_argument("--port_udp", type=int, default=54322, help="Port number")
    parser.add_argument("--no_life", action="store_true", help="Disable life mode on the camera")
    parser.add_argument("--no_awareness", action="store_true", help="Disable basic awareness on the camera")
    args = parser.parse_args()

    try:
        import uvloop

        uvloop.install()
    except Exception:
        pass

    pepper_camera = PepperCamera(args.no_life, args.no_awareness)
    manager = PepperSocketManager(args.host, args.port_tcp, args.port_udp, pepper_camera)

    try:
        await manager.start()
        await pepper_camera.wez_usiadz()
        print("Pepper Camera Client is running.")
        if manager.command_task:
            await manager.command_task
    finally:
        await manager.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

