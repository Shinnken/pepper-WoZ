import socket
import tkinter
import tkinter.messagebox
import customtkinter
import os
import csv
from pepper_app_socket_manager import SocketManager
from tkinter import filedialog
from ssh_deploy_remote import deploy_remote

customtkinter.set_appearance_mode("Dark")  # Modes: "System" (standard), "Dark", "Light"
customtkinter.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"


class App(customtkinter.CTk):
    def __init__(self, socket_manager: SocketManager):
        super().__init__()
        self.socket_manager = socket_manager
        self.ssh_manager = None

        # configure window
        self.title("Pepper App")
        self.geometry(f"{1100}x{580}")
        # self.attributes("-fullscreen", True)
        self.after(0, self._maximize_window)
        # fullscreen but buttons still accessible
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
        self.ip_entry.insert(0, "192.168.1.102")
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

        # removed legacy dialogue_options/scrollable_frame setup in favor of new layout

        self.connect_button.configure(command=self.connect)
        self.say_button.configure(command=self.say_text)
        self.record_toggle_button.configure(state="disabled")
        self.say_button.configure(state="disabled")

        self.dialogue_container = customtkinter.CTkFrame(self)
        self.dialogue_container.grid(row=2, column=2, columnspan=3, padx=20, pady=20, sticky="nsew")
        self.dialogue_container.grid_columnconfigure(0, weight=1)
        self.dialogue_container.grid_columnconfigure(1, weight=1)
        self.dialogue_container.grid_rowconfigure(1, weight=1)

        toggle_frame = customtkinter.CTkFrame(self.dialogue_container)
        toggle_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        toggle_frame.grid_columnconfigure((0, 1), weight=1)

        self.wstep_button = customtkinter.CTkButton(toggle_frame, text="wstęp", command=self.show_start_frame, state="disabled")
        self.wstep_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.dylematy_button = customtkinter.CTkButton(toggle_frame, text="dylematy", command=self.show_problems_frame)
        self.dylematy_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.left_container = customtkinter.CTkFrame(self.dialogue_container)
        self.left_container.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(10, 0))
        self.left_container.grid_rowconfigure(0, weight=1)
        self.left_container.grid_columnconfigure(0, weight=1)

        self.start_frame = customtkinter.CTkFrame(self.left_container)
        self.start_frame.grid(row=0, column=0, sticky="nsew")
        for i in range(5):
            customtkinter.CTkButton(self.start_frame, text=f"greetings {i+1}").grid(row=i, column=0, padx=5, pady=5, sticky="ew")

        self.problems_frame = customtkinter.CTkFrame(self.left_container)
        self.problems_frame.grid(row=0, column=0, sticky="nsew")
        for i in range(5):
            customtkinter.CTkButton(self.problems_frame, text=f"odpowiedzi {i+1}").grid(row=i, column=0, padx=5, pady=5, sticky="ew")
        self.problems_frame.grid_remove()

        self.right_scroll_frame = customtkinter.CTkScrollableFrame(self.dialogue_container)
        self.right_scroll_frame.grid(row=1, column=1, sticky="nsew", pady=(10, 0))
        self.right_scroll_frame.grid_columnconfigure(0, weight=1)
        for row_index, label in enumerate(("afirmacja", "cisza", "nie na temat")):
            group_frame = customtkinter.CTkFrame(self.right_scroll_frame)
            group_frame.grid(row=row_index, column=0, padx=5, pady=(0, 10), sticky="ew")
            group_frame.grid_columnconfigure(0, weight=1)
            for i in range(5):
                customtkinter.CTkButton(group_frame, text=f"{label} {i+1}").grid(row=i, column=0, padx=5, pady=5, sticky="ew")

        self.loading_bar.set(0)
        self.show_start_frame()


    def connect(self):
        ip_value = self.ip_entry.get()
        if not ip_value:
            tkinter.messagebox.showerror("Error", "Please enter an IP address")
            return

        try:

####BEGIN SOCKET
            try:
                self.socket_manager.start()
            except socket.timeout:
                tkinter.messagebox.showerror("Error", "Socket connection timed out. Check connection with Pepper.")
                return
            except Exception as e:
                tkinter.messagebox.showerror("Error", f"Unknown connection error: {e}")
                return
            print("STARTED SOCKET")
####END SOCKET
            deploy_remote(ip_value)
            print("DEPLOYED REMOTE SCRIPT")
####BEGIN SOCKET
            try:
                self.socket_manager.tcp_socket.accept_connection() #blocking
            except socket.timeout:
                tkinter.messagebox.showerror("Error", "Socket connection timed out. Check connection with Pepper.")
                return
            except Exception as e:
                tkinter.messagebox.showerror("Error", f"Unknown connection error: {e}")
                return
####END SOCKET        
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

    def show_start_frame(self):
        self.problems_frame.grid_remove()
        self.start_frame.grid()
        self.wstep_button.configure(state="disabled")
        self.dylematy_button.configure(state="normal")

    def show_problems_frame(self):
        self.start_frame.grid_remove()
        self.problems_frame.grid()
        self.dylematy_button.configure(state="disabled")
        self.wstep_button.configure(state="normal")

    def close_app(self):
        self.socket_manager.handle_command("exit")
        self.destroy()
        print("Application closed.")

    def _maximize_window(self):
        try:
            self.state("zoomed")
        except tkinter.TclError:
            try:
                self.attributes("-zoomed", True)
            except tkinter.TclError:
                screen_width = self.winfo_screenwidth()
                screen_height = self.winfo_screenheight()
                self.geometry(f"{screen_width}x{screen_height}+0+0")
