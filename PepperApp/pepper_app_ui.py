import socket
import tkinter
import tkinter.messagebox
import customtkinter
import os
import csv
from pepper_app_socket_manager import SocketManager
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
        self.button_template_path = os.path.join(os.path.dirname(__file__), "button_layout_template_3.tsv")
        self.button_definitions = self._load_button_definitions(self.button_template_path)
        self._active_scroll_canvas = None
        self._used_button_fg_color = ("#f9cb4d", "#a87b0f")
        self._used_button_hover_color = ("#f0b928", "#8f670d")

        self.dialogue_container = customtkinter.CTkFrame(self)
        self.dialogue_container.grid(row=2, column=2, columnspan=3, padx=20, pady=20, sticky="nsew")
        self.dialogue_container.grid_columnconfigure(0, weight=3, uniform="dialogue_columns")
        self.dialogue_container.grid_columnconfigure(1, weight=1, uniform="dialogue_columns")
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

        self.start_frame = customtkinter.CTkScrollableFrame(self.left_container)
        self.start_frame.grid(row=0, column=0, sticky="nsew")
        self._register_scrollable_frame(self.start_frame)
        start_buttons = self.button_definitions.get("start", {}).get("default", [])
        self._populate_button_list(self.start_frame, start_buttons)

        self.problems_frame = customtkinter.CTkFrame(self.left_container)
        self.problems_frame.grid(row=0, column=0, sticky="nsew")
        self.problems_frame.grid_columnconfigure(0, weight=1)
        self.problems_frame.grid_rowconfigure(1, weight=1)

        self.problem_toggle_container = customtkinter.CTkFrame(self.problems_frame)
        self.problem_toggle_container.grid(row=0, column=0, padx=5, pady=(0, 10), sticky="ew")

        self.problem_frames_container = customtkinter.CTkFrame(self.problems_frame)
        self.problem_frames_container.grid(row=1, column=0, sticky="nsew")
        self.problem_frames_container.grid_rowconfigure(0, weight=1)
        self.problem_frames_container.grid_columnconfigure(0, weight=1)

        problem_items = list(self.button_definitions.get("problems", {}).items())
        if not problem_items:
            problem_items = [("1", [])]

        self.problem_toggle_buttons = []
        self.problem_subframes = {}
        self.problem_frame_keys = []

        for index, (frame_key, button_defs) in enumerate(problem_items):
            key_text = str(frame_key)
            toggle_button = customtkinter.CTkButton(
                self.problem_toggle_container,
                text=key_text,
                command=lambda idx=index: self.show_problem_subframe(idx)
            )
            toggle_button.grid(row=0, column=index, padx=5, sticky="ew")
            self.problem_toggle_container.grid_columnconfigure(index, weight=1)
            self.problem_toggle_buttons.append(toggle_button)

            subframe = customtkinter.CTkScrollableFrame(self.problem_frames_container)
            subframe.grid(row=0, column=0, sticky="nsew")
            self._register_scrollable_frame(subframe)
            self._populate_button_list(subframe, button_defs)
            subframe.grid_remove()

            self.problem_subframes[key_text] = subframe
            self.problem_frame_keys.append(key_text)

        self.active_problem_index = 0
        self.show_problem_subframe(self.active_problem_index)
        self.problems_frame.grid_remove()

        self.right_scroll_frame = customtkinter.CTkScrollableFrame(self.dialogue_container)
        self.right_scroll_frame.grid(row=1, column=1, sticky="nsew", pady=(10, 0))
        self._register_scrollable_frame(self.right_scroll_frame)
        self.right_scroll_frame.grid_columnconfigure(0, weight=1)

        right_items = list(self.button_definitions.get("right", {}).items())
        if not right_items:
            right_items = [("misc", [])]

        for row_index, (group_name, button_defs) in enumerate(right_items):
            group_label = str(group_name)
            if(group_label == "affirmation" or group_label == "silence" or group_label == "off_topic"):
                group_frame = customtkinter.CTkFrame(self.right_scroll_frame)
            else:
                group_frame = customtkinter.CTkScrollableFrame(self.right_scroll_frame, label_text=group_label)
            group_frame.grid(row=row_index, column=0, padx=5, pady=(0, 10), sticky="ew")
            self._populate_button_list(group_frame, button_defs)
            if(group_label == "affirmation" or group_label == "silence" or group_label == "off_topic"):
                continue
            self._register_scrollable_frame(group_frame)

        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)

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

    def _load_button_definitions(self, template_path: str):
        definitions = {
            "start": {"default": []},
            "problems": {},
            "right": {}
        }

        if not os.path.exists(template_path):
            return definitions

        entry_index = 0

        with open(template_path, "r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file, delimiter="\t")
            for row in reader:
                section = (row.get("section") or "").strip().lower()
                group = (row.get("group") or "").strip()
                label = (row.get("label") or "").strip()
                value = (row.get("value") or "").strip()

                if not section:
                    continue

                if not label and value:
                    label = value
                elif not label and not value:
                    continue

                if not value:
                    value = label

                order_text = (row.get("order") or "").strip()
                try:
                    order_value = float(order_text) if order_text else None
                except ValueError:
                    order_value = None

                entry_index += 1
                entry = {"label": label, "value": value, "sequence": entry_index}
                if order_value is not None:
                    entry["order"] = order_value

                if section == "start":
                    bucket = definitions.setdefault("start", {})
                    target_group = group or "default"
                    bucket.setdefault(target_group, []).append(entry)
                elif section in {"problem", "problems"}:
                    bucket = definitions.setdefault("problems", {})
                    target_group = group or "1"
                    bucket.setdefault(target_group, []).append(entry)
                elif section in {"right", "response"}:
                    bucket = definitions.setdefault("right", {})
                    target_group = group or "misc"
                    bucket.setdefault(target_group, []).append(entry)

        definitions.setdefault("start", {}).setdefault("default", [])
        definitions.setdefault("problems", {})
        definitions.setdefault("right", {})
        return definitions

    def _populate_button_list(self, container, button_defs):
        container.grid_columnconfigure(0, weight=1)

        if not button_defs:
            placeholder = customtkinter.CTkLabel(container, text="No options configured")
            placeholder.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
            return

        sorted_definitions = sorted(
            button_defs,
            key=lambda item: (
                0 if item.get("order") is not None else 1,
                item.get("order", 0),
                item.get("sequence", 0)
            )
        )

        for row_index, definition in enumerate(sorted_definitions):
            label = definition.get("label", "")
            value = definition.get("value", label)
            button = customtkinter.CTkButton(
                container,
                text=label
            )
            button.original_fg_color = button.cget("fg_color")
            button.original_hover_color = button.cget("hover_color")
            button.configure(command=lambda payload=value, btn=button: self._handle_template_button_click(btn, payload))
            button.grid(row=row_index, column=0, padx=5, pady=5, sticky="ew")

    def _register_scrollable_frame(self, scroll_frame):
        scroll_frame.grid_columnconfigure(0, weight=1)
        canvas = getattr(scroll_frame, "_parent_canvas", None)

        if canvas is None:
            return

        def _activate(_event, target_canvas=canvas):
            self._active_scroll_canvas = target_canvas

        def _deactivate(_event, target_canvas=canvas):
            if self._active_scroll_canvas is target_canvas:
                self._active_scroll_canvas = None

        inner = getattr(scroll_frame, "_scrollable_frame", None)

        canvas.bind("<Enter>", _activate)
        canvas.bind("<Leave>", _deactivate)
        scroll_frame.bind("<Enter>", _activate)
        scroll_frame.bind("<Leave>", _deactivate)

        if inner is not None:
            inner.bind("<Enter>", _activate)
            inner.bind("<Leave>", _deactivate)

    def _on_mousewheel(self, event):
        canvas = self._active_scroll_canvas
        if canvas is None:
            return

        delta = 0
        if event.delta:
            steps = max(1, abs(event.delta) // 120)
            delta = -steps if event.delta > 0 else steps
        else:
            event_num = getattr(event, "num", None)
            if event_num == 4:
                delta = -1
            elif event_num == 5:
                delta = 1

        if delta:
            canvas.yview_scroll(delta, "units")
            return "break"

    def _handle_template_button_click(self, button, payload):
        self.text_button_event(payload)
        button.configure(fg_color=self._used_button_fg_color, hover_color=self._used_button_hover_color)

    def show_problem_subframe(self, index: int):
        if not self.problem_frame_keys or not self.problem_subframes:
            return

        index = max(0, min(index, len(self.problem_frame_keys) - 1))
        target_key = self.problem_frame_keys[index]
        target_frame = self.problem_subframes.get(target_key)
        if target_frame is None:
            return

        for frame in self.problem_subframes.values():
            frame.grid_remove()
        target_frame.grid(row=0, column=0, sticky="nsew")

        for button_index, button in enumerate(self.problem_toggle_buttons):
            state = "disabled" if button_index == index else "normal"
            button.configure(state=state)

        self.active_problem_index = index

    def show_start_frame(self):
        self.problems_frame.grid_remove()
        self.start_frame.grid()
        self.wstep_button.configure(state="disabled")
        self.dylematy_button.configure(state="normal")

    def show_problems_frame(self):
        self.start_frame.grid_remove()
        self.problems_frame.grid()
        self.show_problem_subframe(self.active_problem_index)
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
