#!./venv/bin/python3
from pepper_app_ui import App


if __name__ == "__main__":
    app = App(socket_manager=None, manual_connection=True)
    app.mainloop()

    