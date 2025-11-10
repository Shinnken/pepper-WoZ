import socket
import tkinter
import tkinter.messagebox
import customtkinter
import os
import csv
import threading
from pepper_app_socket_manager import SocketManager
from ssh_deploy_remote import deploy_remote

customtkinter.set_appearance_mode("Dark")  # Modes: "System" (standard), "Dark", "Light"
customtkinter.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

class App(customtkinter.CTk):
    def __init__(self, socket_manager: SocketManager):
        super().__init__()
        self.socket_manager = socket_manager
        self.ssh_manager = None

        # Adjust this to change the font size of the Say textbox
        self.say_textbox_font_size = 18
        self.say_textbox_font = customtkinter.CTkFont(size=self.say_textbox_font_size)
        # Set to False when you want the Say textbox to be read-only from the keyboard
        self.say_textbox_allow_typing = False
        self._say_textbox_current_state = "normal"

        # Adjust these to change the height of buttons generated from TSV definitions
        self.template_button_height_left = 60
        self.template_button_height_right = 30
        # Adjust this to change the font size used by all buttons
        self.button_font_size = 18
        self.button_font = customtkinter.CTkFont(size=self.button_font_size)

        # configure window
        self.title("Pepper App")
        self.geometry(f"{1100}x{580}")
        # self.attributes("-fullscreen", True)
        self.after(0, self._maximize_window)
        # fullscreen but buttons still accessible
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self._window_icon_image = None
        self._configure_window_icon()


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
        self.grid_columnconfigure(4, weight=1)
        self.grid_columnconfigure(5, weight=1)

        # create IP input and connect button
        # self.ip_entry = customtkinter.CTkEntry(self, placeholder_text="Enter IP")
        self.ip_entry = customtkinter.CTkEntry(self)
        self.ip_entry.insert(0, "192.168.1.102")
        self.ip_entry.grid(row=0, column=0, padx=20, pady=20, sticky="w")
        self.connect_button = customtkinter.CTkButton(self, text="Połącz z Robotem", font=self.button_font)
        self.connect_button.grid(row=0, column=1, padx=20, pady=20, sticky="w")
        self._initialize_button_colors(self.connect_button)

        # create ID Pacjenta label and entry
        self.id_label = customtkinter.CTkLabel(self, text="ID Pacjenta:")
        self.id_label.grid(row=0, column=2, padx=(20, 5), pady=20, sticky="e")
        self.id_entry = customtkinter.CTkEntry(self, width=150)
        self.id_entry.grid(row=0, column=3, padx=(5, 20), pady=20, sticky="w")

        self.id_mode = "GRUPA KONTROLNA"
        self._id_mode_to_set = {
            "GRUPA KONTROLNA": "kontrolna",
            "GRUPA EKSPERYMENTALNA": "badawcza",
        }
        self.id_mode_button = customtkinter.CTkButton(
            self,
            text=self.id_mode,
            width=300,
            height=60,
            command=self.toggle_id_mode,
            font=self.button_font,
        )
        self.id_mode_button.grid(row=0, column=4, padx=(0, 20), pady=20, sticky="w")
        self._initialize_button_colors(self.id_mode_button)

        # create record/stop toggle button and loading bar
        self.record_toggle_button = customtkinter.CTkButton(
            self, 
            text="Record", 
            fg_color="green", 
            hover_color="#006400",  # Dark green for hover
            width=400,  # Increased width
            height=60,  # Scalable height
            command=self.toggle_recording,
            font=self.button_font,
        )
        self.record_toggle_button.grid(row=0, column=5, padx=20, pady=20, sticky="ew")  # Moved to a new column
        self._initialize_button_colors(self.record_toggle_button)
        self.loading_bar = customtkinter.CTkProgressBar(self, progress_color="#a60d02")
        self.loading_bar.grid(row=1, column=2, columnspan=4, padx=20, pady=10, sticky="ew")  # Stretch under controls

        # create large textbox and say button
        self.large_textbox = customtkinter.CTkTextbox(
            self,
            width=300,
            height=100,
            font=self.say_textbox_font,
        )
        self.large_textbox.grid(row=2, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="nsew")
        self._apply_say_textbox_editable_state()
        self.large_textbox.bind("<Return>", self._handle_say_textbox_enter, add="+")
        self.large_textbox.bind("<KP_Enter>", self._handle_say_textbox_enter, add="+")
        self.say_button = customtkinter.CTkButton(self, text="Say", width=120, height=40, font=self.button_font)
        self.say_button.grid(row=3, column=0, columnspan=2, padx=20, pady=(0, 20), sticky="ew")
        self._initialize_button_colors(self.say_button)
        self.say_button.bind("<Return>", self._handle_say_button_enter, add="+")
        self.say_button.bind("<KP_Enter>", self._handle_say_button_enter, add="+")

        # removed legacy dialogue_options/scrollable_frame setup in favor of new layout

        self.button_template_path = os.path.join(os.path.dirname(__file__), "button_layout_template_0.tsv")
        self.button_definitions, available_sets = self._load_button_definitions(self.button_template_path)
        self._available_button_sets = tuple(available_sets)
        self._available_button_sets_set = set(self._available_button_sets)
        initial_set = (self._id_mode_to_set.get(self.id_mode, "") or "").strip().lower()
        if initial_set and initial_set in self._available_button_sets_set:
            self._default_template_set = initial_set
        elif self._available_button_sets:
            self._default_template_set = self._available_button_sets[0]
        else:
            self._default_template_set = "default"
        self._active_scroll_canvas = None
        self._used_button_fg_color = ("#f9cb4d", "#a87b0f")
        self._used_button_hover_color = ("#f0b928", "#8f670d")
        self._disabled_button_fg_color = ("#3b3b3b", "#333333")
        self._disabled_button_hover_color = ("#3b3b3b", "#333333")
        self._disabled_button_text_color = "#1f6aa5"

        self.connect_button.configure(command=self.connect)
        self.say_button.configure(command=self.say_text)
        self._set_button_state(self.record_toggle_button, "disabled")
        self._set_button_state(self.say_button, "disabled")

        self.dialogue_container = customtkinter.CTkFrame(self)
        self.dialogue_container.grid(row=2, column=2, columnspan=4, padx=20, pady=20, sticky="nsew")
        self.dialogue_container.grid_columnconfigure(0, weight=2)
        self.dialogue_container.grid_columnconfigure(1, weight=1)
        self.dialogue_container.grid_rowconfigure(1, weight=1)

        toggle_frame = customtkinter.CTkFrame(self.dialogue_container)
        toggle_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        toggle_frame.grid_columnconfigure((0, 1), weight=1)

        self.wstep_button = customtkinter.CTkButton(toggle_frame, text="Wstęp + Zakończenie", command=self.show_start_frame, font=self.button_font)
        self.wstep_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.dylematy_button = customtkinter.CTkButton(toggle_frame, text="Dylematy ", command=self.show_problems_frame, font=self.button_font)
        self.dylematy_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self._initialize_button_colors(self.wstep_button)
        self._initialize_button_colors(self.dylematy_button)

        self.left_container = customtkinter.CTkFrame(self.dialogue_container)
        self.left_container.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(10, 0))
        self.left_container.grid_rowconfigure(0, weight=1)
        self.left_container.grid_columnconfigure(0, weight=1)

        self.start_frame_container = customtkinter.CTkFrame(self.left_container)
        self.start_frame_container.grid(row=0, column=0, sticky="nsew")
        self.start_frame_container.grid_rowconfigure(0, weight=1)
        self.start_frame_container.grid_columnconfigure(0, weight=1)

        self.start_frame = customtkinter.CTkScrollableFrame(self.start_frame_container)
        self.start_frame.grid(row=0, column=0, sticky="nsew")
        self._register_scrollable_frame(self.start_frame)
        start_buttons = self.button_definitions.get("start", {}).get("default", [])
        self._populate_button_list(self.start_frame, start_buttons, button_height=self.template_button_height_left)

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
                command=lambda idx=index: self.show_problem_subframe(idx),
                font=self.button_font,
            )
            toggle_button.grid(row=0, column=index, padx=5, sticky="ew")
            self.problem_toggle_container.grid_columnconfigure(index, weight=1)
            self._initialize_button_colors(toggle_button)
            self.problem_toggle_buttons.append(toggle_button)

            subframe = customtkinter.CTkScrollableFrame(self.problem_frames_container)
            subframe.grid(row=0, column=0, sticky="nsew")
            self._register_scrollable_frame(subframe)
            self._populate_button_list(subframe, button_defs, button_height=self.template_button_height_left)
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
            if(group_label in {"affirmation", "silence", "off_topic", "misc"}):
                group_frame = customtkinter.CTkFrame(self.right_scroll_frame)
            else:
                group_frame = customtkinter.CTkScrollableFrame(self.right_scroll_frame, label_text=group_label)
            group_frame.grid(row=row_index, column=0, padx=5, pady=(0, 10), sticky="ew")
            self._populate_button_list(group_frame, button_defs, button_height=self.template_button_height_right)
            if(group_label in {"affirmation", "silence", "off_topic", "misc"}):
                continue
            self._register_scrollable_frame(group_frame)

        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)

        self.loading_bar.set(0)
        self.show_start_frame()
        self.after(0, self._equalize_left_panel_width)




    def _threaded_connect(self, ip_value):
        """
        Runs the blocking connection logic in a separate thread.
        """
        try:
            # --- BLOCK 1 ---
            try:
                self.socket_manager.start()
            except socket.timeout:
                # Use .after() to safely call a UI function from this thread
                self.after(0, lambda: tkinter.messagebox.showerror("Error", "Socket start timed out. Check connection."))
                return
            except Exception as e:
                self.after(0, lambda: tkinter.messagebox.showerror("Error", f"Socket start error: {e}"))
                return
            
            # --- BLOCK 2 ---
            # Note: deploy_remote needs to be thread-safe
            # Assuming it's a blocking function (like subprocess.run)
            deploy_remote(ip_value) 
            
            # --- BLOCK 3 ---
            try:
                self.socket_manager.tcp_socket.accept_connection() #blocking
            except socket.timeout:
                self.after(0, lambda: tkinter.messagebox.showerror("Error", "Socket accept timed out. Pepper app not started?"))
                return
            except Exception as e:
                self.after(0, lambda: tkinter.messagebox.showerror("Error", f"Socket accept error: {e}"))
                return

            # --- SUCCESS ---
            # All blocks finished. Now, update the UI.
            tkinter.messagebox.showinfo("Success", "Connection established successfully!")
            # We MUST use self.after() to safely tell the main UI thread
            # to run these functions.
            def _update_ui_on_success():
                self._set_button_state(self.say_button, "normal")
                self._set_button_state(self.record_toggle_button, "normal")
                self.loading_bar.stop()
                self.loading_bar.set(0)
                # Re-enable connect button *only* if you have disconnect logic
                # For now, we'll leave it disabled
                # self._set_button_state(self.connect_button, "normal")
            
            self.after(0, _update_ui_on_success)

        except Exception as e:
            # Catch-all for other errors (e.g., deploy_remote failure)
            self.after(0, lambda: tkinter.messagebox.showerror("Error", f"Connection failed: {e}"))
            # Also re-enable the connect button so they can try again
            self.after(0, self._re_enable_connect_button)



    def connect(self):
        ip_value = self.ip_entry.get()
        if not ip_value:
            tkinter.messagebox.showerror("Error", "Please enter an IP address")
            return
            
        # 1. Disable the connect button immediately
        self._set_button_state(self.connect_button, "disabled")
        
        # 2. Show a loading indicator
        self.loading_bar.configure(mode="indeterminate")
        self.loading_bar.start()

        # 3. Create and start the worker thread
        #    We pass the ip_value as an argument
        connect_thread = threading.Thread(
            target=self._threaded_connect, 
            args=(ip_value,),
            daemon=True  # daemon=True ensures thread exits when app closes
        )
        connect_thread.start()
        
        # The connect() function now finishes instantly,
        # leaving the UI responsive while the thread runs.

    def _re_enable_connect_button(self):
        """Helper to re-enable UI on failure."""
        self.loading_bar.stop()
        self.loading_bar.set(0)
        self._set_button_state(self.connect_button, "normal")





    def connect_old(self):
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
        
        self._set_button_state(self.say_button, "normal")
        self._set_button_state(self.record_toggle_button, "normal")
        self._set_button_state(self.connect_button, "disabled")


    def text_button_event(self, text):
        self._set_large_textbox_content(text)

    def say_text(self):
        text = self.large_textbox.get("0.0", "end")
        self.socket_manager.handle_command("speak", text)
        # self.large_textbox.delete("0.0", "end")

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

    def toggle_id_mode(self):
        """Flip the patient mode between control and exam labels."""
        self.id_mode = "GRUPA EKSPERYMENTALNA" if self.id_mode == "GRUPA KONTROLNA" else "GRUPA KONTROLNA"
        self.id_mode_button.configure(text=self.id_mode)
        self._default_template_set = self._current_template_set_key()

    def _load_button_definitions(self, template_path: str):
        definitions = {
            "start": {"default": []},
            "problems": {},
            "right": {}
        }
        available_sets = set()
        entry_lookup = {}
        sequence_counter = 0

        if not os.path.exists(template_path):
            if not available_sets:
                available_sets.add("default")
            return definitions, tuple(sorted(available_sets))

        with open(template_path, "r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file, delimiter="\t")
            for row in reader:
                raw_set = (row.get("set") or "").strip()
                normalized_set = raw_set.lower() if raw_set else "default"
                available_sets.add(normalized_set)

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

                section_key = None
                target_group = None

                if section == "start":
                    section_key = "start"
                    target_group = group or "default"
                elif section in {"problem", "problems"}:
                    section_key = "problems"
                    target_group = group or "1"
                elif section in {"right", "response"}:
                    section_key = "right"
                    target_group = group or "misc"
                else:
                    continue

                bucket = definitions.setdefault(section_key, {})
                items = bucket.setdefault(target_group, [])
                entry_key = (section_key, target_group, label)
                entry = entry_lookup.get(entry_key)

                if entry is None:
                    sequence_counter += 1
                    entry = {
                        "label": label,
                        "sequence": sequence_counter,
                        "values": {}
                    }
                    if order_value is not None:
                        entry["order"] = order_value
                    entry["value"] = value
                    items.append(entry)
                    entry_lookup[entry_key] = entry
                else:
                    if order_value is not None and entry.get("order") is None:
                        entry["order"] = order_value

                entry["values"][normalized_set] = value

        definitions.setdefault("start", {}).setdefault("default", [])
        definitions.setdefault("problems", {})
        definitions.setdefault("right", {})

        if not available_sets:
            available_sets.add("default")

        ordered_sets = list(available_sets)
        if "default" in available_sets:
            ordered_sets.sort()
            ordered_sets.insert(0, ordered_sets.pop(ordered_sets.index("default")))
        else:
            ordered_sets.sort()

        return definitions, tuple(ordered_sets)

    def _populate_button_list(self, container, button_defs, button_height=None):
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

        resolved_height = button_height
        if resolved_height is None:
            resolved_height = getattr(self, "template_button_height_left", None)

        for row_index, definition in enumerate(sorted_definitions):
            label = definition.get("label", "")
            button_kwargs = {"text": label}
            if resolved_height:
                button_kwargs["height"] = resolved_height
            button_font = getattr(self, "button_font", None)
            if button_font is not None:
                button_kwargs["font"] = button_font
            button = customtkinter.CTkButton(container, **button_kwargs)
            self._initialize_button_colors(button)
            button.configure(command=lambda entry=definition, btn=button: self._handle_template_button_click(btn, entry))
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

    def _handle_template_button_click(self, button, entry):
        payload = self._resolve_entry_value(entry)
        self.text_button_event(payload)
        button._active_override_colors = (self._used_button_fg_color, self._used_button_hover_color)
        button.configure(fg_color=self._used_button_fg_color, hover_color=self._used_button_hover_color)

    def _current_template_set_key(self):
        mapped = (self._id_mode_to_set.get(self.id_mode, "") or "").strip().lower()
        if mapped and mapped in self._available_button_sets_set:
            return mapped
        if mapped and mapped in self._available_button_sets:
            return mapped
        derived = (self.id_mode or "").strip().lower()
        if derived and derived in self._available_button_sets_set:
            return derived
        if derived and derived in self._available_button_sets:
            return derived
        if self._default_template_set:
            return self._default_template_set
        if self._available_button_sets:
            return self._available_button_sets[0]
        return "default"

    def _resolve_entry_value(self, entry):
        values = entry.get("values") or {}
        active_set = self._current_template_set_key()

        if active_set in values:
            return values[active_set]

        if self._default_template_set and self._default_template_set in values:
            return values[self._default_template_set]

        for fallback in values.values():
            return fallback

        return entry.get("label", "")

    def _equalize_left_panel_width(self):
        try:
            self.update_idletasks()
        except tkinter.TclError:
            return

        start_width = 0
        problems_width = 0

        if hasattr(self, "start_frame_container"):
            try:
                start_width = self.start_frame_container.winfo_reqwidth()
            except tkinter.TclError:
                start_width = 0

        if hasattr(self, "problems_frame"):
            try:
                problems_width = self.problems_frame.winfo_reqwidth()
            except tkinter.TclError:
                problems_width = 0

        target_width = max(start_width, problems_width)
        if target_width <= 0:
            return

        self.dialogue_container.grid_columnconfigure(0, minsize=target_width)

    def _apply_say_textbox_editable_state(self):
        textbox = getattr(self, "large_textbox", None)
        if textbox is None:
            return

        allow_typing = getattr(self, "say_textbox_allow_typing", True)
        target_state = "normal" if allow_typing else "disabled"

        try:
            textbox.configure(state=target_state)
        except tkinter.TclError:
            self._say_textbox_current_state = "normal"
            return

        self._say_textbox_current_state = target_state

    def set_say_textbox_allow_typing(self, allow_typing: bool):
        """Convenience helper to toggle keyboard editing at runtime."""
        self.say_textbox_allow_typing = bool(allow_typing)
        self._apply_say_textbox_editable_state()

    def set_button_font_size(self, size):
        """Update the shared button font and remember the new size."""
        try:
            resolved_size = max(1, int(size))
        except (TypeError, ValueError):
            return

        self.button_font_size = resolved_size

        button_font = getattr(self, "button_font", None)
        if button_font is None:
            self.button_font = customtkinter.CTkFont(size=resolved_size)
        else:
            try:
                button_font.configure(size=resolved_size)
            except tkinter.TclError:
                self.button_font = customtkinter.CTkFont(size=resolved_size)

    def _set_large_textbox_content(self, text):
        textbox = getattr(self, "large_textbox", None)
        if textbox is None:
            return

        previous_state = getattr(self, "_say_textbox_current_state", "normal")
        temporary_unlock = previous_state == "disabled"

        if temporary_unlock:
            try:
                textbox.configure(state="normal")
            except tkinter.TclError:
                temporary_unlock = False
            else:
                self._say_textbox_current_state = "normal"

        try:
            textbox.delete("0.0", "end")
            textbox.insert("0.0", text)
        finally:
            if temporary_unlock:
                try:
                    textbox.configure(state="disabled")
                except tkinter.TclError:
                    self._say_textbox_current_state = "normal"
                else:
                    self._say_textbox_current_state = "disabled"

    def _handle_say_textbox_enter(self, event):
        """Trigger Say when Return is pressed inside the textbox."""
        modifiers = getattr(event, "state", 0)
        if modifiers & (1 | 4 | 8):  # ignore Shift/Ctrl/Alt+Enter to keep newlines available
            return None

        if getattr(self.say_button, "cget", None) and self.say_button.cget("state") == "disabled":
            return "break"

        self.say_text()
        return "break"

    def _handle_say_button_enter(self, _event):
        """Allow pressing Enter on the Say button itself."""
        if getattr(self.say_button, "cget", None) and self.say_button.cget("state") == "disabled":
            return "break"

        self.say_text()
        return "break"

    def _initialize_button_colors(self, button):
        if button is None:
            return

        if not hasattr(button, "_original_fg_color"):
            button._original_fg_color = button.cget("fg_color")
        if not hasattr(button, "_original_hover_color"):
            button._original_hover_color = button.cget("hover_color")
        if not hasattr(button, "_original_text_color"):
            button._original_text_color = button.cget("text_color")

    def _restore_button_colors(self, button):
        self._initialize_button_colors(button)
        active_override = getattr(button, "_active_override_colors", None)

        if active_override:
            fg_color, hover_color = active_override
        else:
            fg_color = getattr(button, "_original_fg_color", None)
            hover_color = getattr(button, "_original_hover_color", None)

        kwargs = {}
        if fg_color is not None:
            kwargs["fg_color"] = fg_color
        if hover_color is not None:
            kwargs["hover_color"] = hover_color

        original_text_color = getattr(button, "_original_text_color", None)
        if original_text_color not in (None, ""):
            kwargs["text_color"] = original_text_color

        if kwargs:
            button.configure(**kwargs)

    def _set_button_state(self, button, state: str):
        self._initialize_button_colors(button)
        button.configure(state=state)

        if state == "disabled":
            kwargs = {
                "fg_color": self._disabled_button_fg_color,
                "hover_color": self._disabled_button_hover_color,
            }
            if self._disabled_button_text_color:
                kwargs["text_color"] = self._disabled_button_text_color
            button.configure(**kwargs)
        else:
            self._restore_button_colors(button)

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
            self._set_button_state(button, state)

        self.active_problem_index = index

    def show_start_frame(self):
        self.problems_frame.grid_remove()
        self.start_frame_container.grid()
        self._set_button_state(self.wstep_button, "disabled")
        self._set_button_state(self.dylematy_button, "normal")
        self._equalize_left_panel_width()

    def show_problems_frame(self):
        self.start_frame_container.grid_remove()
        self.problems_frame.grid()
        self.show_problem_subframe(self.active_problem_index)
        self._set_button_state(self.dylematy_button, "disabled")
        self._set_button_state(self.wstep_button, "normal")
        self._equalize_left_panel_width()

    def close_app(self):
        self.socket_manager.handle_command("exit")
        self.destroy()
        print("Application closed.")

    def _configure_window_icon(self):
        icon_directory = os.path.dirname(__file__)
        candidate_names = ["icon.png", "icon.ico"]

        for name in candidate_names:
            icon_path = os.path.join(icon_directory, name)
            if not os.path.exists(icon_path):
                continue

            try:
                if icon_path.lower().endswith(".ico") and os.name == "nt":
                    self.iconbitmap(icon_path)
                else:
                    image = tkinter.PhotoImage(file=icon_path)
                    self.iconphoto(True, image)
                    self._window_icon_image = image
                return
            except tkinter.TclError as error:
                print(f"Warning: failed to load window icon '{icon_path}': {error}")

        # no suitable icon found or loaded; keep default without raising

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
