import socket
import tkinter
import tkinter.messagebox
import customtkinter
import os
import csv
from pepper_app_socket_manager import SocketManager
from pepper_app_ssh_manager import SSHManager
from tkinter import filedialog

customtkinter.set_appearance_mode("Dark")  # Modes: "System" (standard), "Dark", "Light"
customtkinter.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"


class App(customtkinter.CTk):
    def __init__(self, socket_manager: SocketManager):
        super().__init__()
        self.socket_manager = socket_manager

        # configure window
        self.title("Pepper App")
        self.geometry(f"{1100}x{580}")
        self.protocol("WM_DELETE_WINDOW", self.close_app)

        # configure grid layout (4x4)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure((2, 3), weight=0)
        self.grid_rowconfigure((0, 1, 2), weight=1)

        # adjust row/column weights
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_columnconfigure(2, weight=1)
        self.grid_columnconfigure(3, weight=1)

        # create IP input and connect button
        # self.ip_entry = customtkinter.CTkEntry(self, placeholder_text="Enter IP")
        self.ip_entry = customtkinter.CTkEntry(self)
        self.ip_entry.insert(0, "192.168.1.110")
        self.ip_entry.grid(row=0, column=0, padx=20, pady=20, sticky="w")
        self.connect_button = customtkinter.CTkButton(self, text="Connect")
        self.connect_button.grid(row=0, column=1, padx=20, pady=20, sticky="w")

        # create ID Pacjenta label and entry
        self.id_label = customtkinter.CTkLabel(self, text="ID Pacjenta:")
        self.id_label.grid(row=0, column=2, padx=(20, 5), pady=20, sticky="e")
        self.id_entry = customtkinter.CTkEntry(self, width=150)
        self.id_entry.grid(row=0, column=3, padx=(5, 20), pady=20, sticky="w")

        # create record/stop toggle button and loading bar
        self.record_toggle_button = customtkinter.CTkButton(
            self, 
            text="Record", 
            fg_color="green", 
            hover_color="#006400",  # Dark green for hover
            width=400,  # Increased width
            height=60,  # Scalable height
            command=self.toggle_recording
        )
        self.record_toggle_button.grid(row=0, column=4, padx=20, pady=20, sticky="ew")  # Moved to a new column
        self.loading_bar = customtkinter.CTkProgressBar(self, progress_color="#a60d02")
        self.loading_bar.grid(row=1, column=2, columnspan=3, padx=20, pady=10, sticky="ew")  # Adjusted columnspan

        # create large textbox and say button
        self.large_textbox = customtkinter.CTkTextbox(self, width=300, height=100)
        self.large_textbox.grid(row=2, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="nsew")
        self.say_button = customtkinter.CTkButton(self, text="Say", width=120, height=40)
        self.say_button.grid(row=3, column=0, columnspan=2, padx=20, pady=(0, 20), sticky="ew")

        # attempt to read from an Excel-like CSV file
        script_folder = os.path.dirname(os.path.abspath(__file__))
        dialogue_file = os.path.join(script_folder, "dialogue_options.csv")
        if os.path.isfile(dialogue_file):
            dialogue_options = {}
            with open(dialogue_file, "r", newline="", encoding="utf-8-sig") as f:
                content = f.read()
                delim = ";" if ";" in content else ","
                f.seek(0)
                reader = csv.reader(f, delimiter=delim)
                for row in reader:
                    if len(row) >= 2:
                        dialogue_options[row[0]] = row[1]
        else:
            new_path = r"C:\Users\british\Downloads\Pepper\Pepper (1)\Pepper\bin\Dialogi.csv"

            if new_path and os.path.isfile(new_path):
                dialogue_options = {}
                with open(new_path, "r", newline="", encoding="utf-8-sig") as f:
                    content = f.read()
                    delim = ";" if ";" in content else ","
                    f.seek(0)
                    reader = csv.reader(f, delimiter=delim)
                    for row in reader:
                        if len(row) >= 2:
                            dialogue_options[row[0]] = row[1]
            else:
                dialogue_options = {f"Text {i+1}": f"Text {i+1}" for i in range(18)}

        # create scrollable frame with X text buttons
        self.scrollable_frame = customtkinter.CTkScrollableFrame(self, label_text="Text Buttons", width=400)
        self.scrollable_frame.bind_all("<Button-4>", lambda e: self.scrollable_frame._parent_canvas.yview("scroll", -1, "units"))
        self.scrollable_frame.bind_all("<Button-5>", lambda e: self.scrollable_frame._parent_canvas.yview("scroll", 1, "units"))
        self.scrollable_frame.grid(row=2, column=2, columnspan=3, padx=20, pady=20, sticky="nsew")  # Adjusted columnspan
        self.scrollable_frame.grid_columnconfigure((0, 1, 2), weight=1)


        for idx, (key, button_text) in enumerate(dialogue_options.items()):

            row = idx // 3
            col = idx % 3
            # Create a button with a maximum width of 20 characters
            # and a label that truncates the text if it's too long
            button_label = key[:20] + "..." if len(key) > 20 else key
            btn = customtkinter.CTkButton(
                self.scrollable_frame,
                text=button_label,
                width=120,
                height=60,
                command=lambda txt=button_text: self.text_button_event(txt)
            )
            btn.grid(row=row, column=col, padx=10, pady=5, sticky="ew")

        self.connect_button.configure(command=self.connect)
        self.say_button.configure(command=self.say_text)
        self.record_toggle_button.configure(state="disabled")
        self.say_button.configure(state="disabled")
        self.loading_bar.set(0)


    def connect(self):
        ip_value = self.ip_entry.get()
        if not ip_value:
            tkinter.messagebox.showerror("Error", "Please enter an IP address")
            return
        
        try:
            try:
                self.socket_manager.start()
            except socket.timeout:
                tkinter.messagebox.showerror("Error", "Socket connection timed out. Check connection with Pepper.")
                return
            except Exception as e:
                tkinter.messagebox.showerror("Error", f"Unknown connection error: {e}")
                return
            print("STARTED SOCKET")


            ssh = SSHManager(username="nao", password="nao")
            ssh.set_target(host=ip_value, port=22)
            try:
                ssh.connect()
            except Exception as e:
                tkinter.messagebox.showerror("Error", f"SSH connection error: {e}")
                return
            print("SSH CONNECTED")
            # TODO: Replace static IP with dynamic one of current pc
            ssh.execute_command("python /home/nao/script/pepper_camera_service.py --host 192.168.50.132")
            print("Pepper camera service started")
            


            try:
                self.socket_manager.tcp_socket.accept_connection() #blocking # TU SIE BLOKUJE I TIMEOUTUJE
                self.socket_manager.is_connected = True  # Set connection flag
            except socket.timeout:
                tkinter.messagebox.showerror("Error", "Socket connection timed out. Check connection with Pepper.")
                return
            except Exception as e:
                tkinter.messagebox.showerror("Error", f"Unknown connection error: {e}")
                return
            print("ACCEPTED SOCKET")

        except Exception as e:
            tkinter.messagebox.showerror("Error", f"Error: {e}")
            return
        except ValueError as e:
            tkinter.messagebox.showerror("Error", f"Invalid IP address format: {e}")
            return
        

        
        self.say_button.configure(state="normal")
        self.record_toggle_button.configure(state="normal")
        self.connect_button.configure(state="disabled")

    def text_button_event(self, text):
        self.large_textbox.delete("0.0", "end")
        self.large_textbox.insert("0.0", text)

    def say_text(self):
        text = self.large_textbox.get("0.0", "end")
        self.socket_manager.handle_command("speak", text)
        self.large_textbox.delete("0.0", "end")

    def toggle_recording(self):
        if self.record_toggle_button.cget("text") == "Record":
            patient_id = self.id_entry.get()
            if not patient_id:
                tkinter.messagebox.showerror("Error", "Please enter a Patient ID")
                return
            self.socket_manager.handle_command("start", patient_id)
            self.record_toggle_button.configure(
                text="Stop", 
                fg_color="red", 
                hover_color="#8B0000"  # Dark red for hover
            )
            self.loading_bar.configure(mode="indeterminate")
            self.loading_bar.start()
        else:
            self.socket_manager.handle_command("stop")
            self.record_toggle_button.configure(
                text="Record", 
                fg_color="green", 
                hover_color="#006400"  # Dark green for hover
            )
            self.loading_bar.stop()
            self.loading_bar.configure(mode="determinate")
            self.loading_bar.set(1)

    def close_app(self):
        try:
            self.socket_manager.handle_command("exit")
        except Exception as e:
            print(f"Error during cleanup: {e}")
        finally:
            self.destroy()
            print("Application closed.")
        print("Application closed.")
