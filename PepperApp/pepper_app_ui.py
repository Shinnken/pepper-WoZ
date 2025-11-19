import socket
import tkinter
import tkinter.messagebox
import customtkinter
import os
import csv
import threading
from pepper_app_socket_manager import SocketManager
from ssh_deploy_remote import deploy_remote

customtkinter.set_appearance_mode("Dark")
customtkinter.set_default_color_theme("blue")


class App(customtkinter.CTk):
    def __init__(self, socket_manager: SocketManager):
        super().__init__()
        self.socket_manager = socket_manager
        self.ssh_manager = None

        self._init_state()
        self._configure_window()
        self._build_top_controls()
        self._load_button_templates()
        self._build_dialogue_layout()
        self._bind_global_events()

        self.loading_bar.set(0)
        self.show_start_frame()
        self.after(0, self._equalize_left_panel_width)

    def connect(self):
        ip_value = self.ip_entry.get().strip()
        if not ip_value:
            tkinter.messagebox.showerror("Error", "Please enter an IP address")
            return

        self._set_button_state(self.connect_button, "disabled")
        self.loading_bar.configure(mode="indeterminate")
        self.loading_bar.start()

        threading.Thread(
            target=self._threaded_connect,
            args=(ip_value,),
            daemon=True,
        ).start()

    def say_text(self):
        text = self.large_textbox.get("0.0", "end")
        pending_button = getattr(self, "_pending_template_button", None)
        self.socket_manager.handle_command("speak", text)
        if pending_button is not None:
            self._mark_template_button_used(pending_button)
            self._pending_template_button = None

    def toggle_recording(self):
        if getattr(self, "_stop_in_progress", False):
            print("Stop already in progress; ignoring toggle.")
            return
        is_starting = self.record_toggle_button.cget("text") == "Record"
        if is_starting:
            patient_id = self.id_entry.get().strip()
            if not patient_id:
                tkinter.messagebox.showerror("Error", "Please enter a Patient ID")
                return
            self.socket_manager.handle_command("start", patient_id)
            self.record_toggle_button.configure(
                text="Stop",
                fg_color="red",
                hover_color="#8B0000",
            )
            self.loading_bar.configure(mode="indeterminate")
            self.loading_bar.start()
            return

        self._stop_in_progress = True
        self._set_button_state(self.record_toggle_button, "disabled")
        self.loading_bar.configure(mode="indeterminate")
        self.loading_bar.start()
        threading.Thread(target=self._async_stop_recording, daemon=True).start()

    def select_id_mode(self, target_mode):
        if not target_mode:
            return

        normalized_target = target_mode.strip().lower()
        canonical_mode = None
        for mode_label in self._id_mode_to_set.keys():
            if mode_label.lower() == normalized_target:
                canonical_mode = mode_label
                break

        if canonical_mode is None:
            canonical_mode = "GRUPA KONTROLNA"

        if canonical_mode != self.id_mode:
            self.id_mode = canonical_mode
            self._default_template_set = self._current_template_set_key()

        self._update_id_mode_buttons()

    def _update_id_mode_buttons(self):
        button_map = getattr(self, "_id_mode_buttons", None) or {}
        if not button_map:
            return

        for mode_label, button in button_map.items():
            if button is None:
                continue

            target_state = "disabled" if mode_label == self.id_mode else "normal"
            self._set_button_state(button, target_state)

    def show_start_frame(self):
        self.problems_frame.grid_remove()
        self.start_frame.grid()
        self._set_button_state(self.wstep_button, "disabled")
        self._set_button_state(self.dylematy_button, "normal")
        self._equalize_left_panel_width()

    def show_problems_frame(self):
        self.start_frame.grid_remove()
        self.problems_frame.grid()
        self.show_problem_subframe(self.active_problem_index)
        self._set_button_state(self.dylematy_button, "disabled")
        self._set_button_state(self.wstep_button, "normal")
        self._equalize_left_panel_width()

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

        target_frame.grid(row=1, column=0, sticky="nsew")

        for button_index, button in enumerate(self.problem_toggle_buttons):
            state = "disabled" if button_index == index else "normal"
            self._set_button_state(button, state)

        self.active_problem_index = index

    def text_button_event(self, text):
        self._set_large_textbox_content(text)

    def set_say_textbox_allow_typing(self, allow_typing: bool):
        self.say_textbox_allow_typing = bool(allow_typing)
        self._apply_say_textbox_editable_state()

    def set_button_font_size(self, size):
        try:
            resolved_size = max(1, int(size))
        except (TypeError, ValueError):
            return

        self.button_font_size = resolved_size

        if self.button_font is None:
            self.button_font = customtkinter.CTkFont(size=resolved_size)
            return

        try:
            self.button_font.configure(size=resolved_size)
        except tkinter.TclError:
            self.button_font = customtkinter.CTkFont(size=resolved_size)

    def close_app(self):
        self.socket_manager.handle_command("exit")
        self.destroy()
        print("Application closed.")

    def toggle_power(self):
        turning_off = self.power_button.cget("text") == "Wyłącz"
        command = "sleep" if turning_off else "wake"
        try:
            self.socket_manager.handle_command(command)
        except Exception as exc:
            tkinter.messagebox.showerror("Power command failed", str(exc))
            return

        if turning_off:
            self.power_button.configure(
                text="Włącz",
                fg_color="#006400",
                hover_color="#004d00",
            )
        else:
            self.power_button.configure(
                text="Wyłącz",
                fg_color="#c96100",
                hover_color="#9f4c00",
            )

    def _async_stop_recording(self):
        error_message = None
        try:
            self.socket_manager.handle_command("stop")
        except Exception as exc:
            error_message = str(exc)
        finally:
            self.after(0, lambda: self._finish_stop_recording(error_message))

    def _finish_stop_recording(self, error_message=None):
        self._stop_in_progress = False
        self.loading_bar.stop()
        self.loading_bar.configure(mode="determinate")
        self.loading_bar.set(1)
        self.record_toggle_button.configure(
            text="Record",
            fg_color="green",
            hover_color="#006400",
        )
        self._set_button_state(self.record_toggle_button, "normal")
        if error_message:
            tkinter.messagebox.showerror("Stop failed", error_message)

    def _threaded_connect(self, ip_value):
        try:
            try:
                self.socket_manager.start()
            except socket.timeout:
                self.after(0, lambda: tkinter.messagebox.showerror("Error", "Socket start timed out. Check connection."))
                return
            except Exception as exc:
                error_message = f"Socket start error: {exc}"
                self.after(0, lambda msg=error_message: tkinter.messagebox.showerror("Error", msg))
                return

            deploy_remote(ip_value)

            try:
                self.socket_manager.tcp_socket.accept_connection()
            except socket.timeout:
                self.after(0, lambda: tkinter.messagebox.showerror("Error", "Socket accept timed out. Pepper app not started?"))
                return
            except Exception as exc:
                error_message = f"Socket accept error: {exc}"
                self.after(0, lambda msg=error_message: tkinter.messagebox.showerror("Error", msg))
                return

            self.after(0, self._handle_connection_success)
        except Exception as exc:
            error_message = f"Connection failed: {exc}"
            self.after(0, lambda msg=error_message: tkinter.messagebox.showerror("Error", msg))
            self.after(0, self._re_enable_connect_button)

    def _handle_connection_success(self):
        tkinter.messagebox.showinfo("Success", "Connection established successfully!")
        self._set_button_state(self.say_button, "normal")
        self._set_button_state(self.record_toggle_button, "normal")
        self._set_button_state(self.power_button, "normal")
        self.loading_bar.stop()
        self.loading_bar.set(0)

    def _re_enable_connect_button(self):
        self.loading_bar.stop()
        self.loading_bar.set(0)
        self._set_button_state(self.connect_button, "normal")

    def _init_state(self):
        self.say_textbox_font_size = 18
        self.say_textbox_font = customtkinter.CTkFont(size=self.say_textbox_font_size)
        self.say_textbox_allow_typing = False
        self._say_textbox_current_state = "normal"

        self.template_button_height_left = 60
        self.template_button_height_right = 30
        self.button_font_size = 18
        self.button_font = customtkinter.CTkFont(size=self.button_font_size)

        self.id_mode = "GRUPA KONTROLNA"
        self._id_mode_to_set = {
            "GRUPA KONTROLNA": "kontrolna",
            "GRUPA EKSPERYMENTALNA": "badawcza",
        }

        self._used_button_fg_color = ("#f9cb4d", "#a87b0f")
        self._used_button_hover_color = ("#f0b928", "#8f670d")
        self._disabled_button_fg_color = ("#3b3b3b", "#333333")
        self._disabled_button_hover_color = ("#3b3b3b", "#333333")
        self._disabled_button_text_color = "#1f6aa5"
        self._active_scroll_canvas = None
        self._left_content_requested_width = 0
        self._window_icon_image = None
        self._pending_template_button = None
        self._stop_in_progress = False
        self._id_mode_buttons = {}
        try:
            self._windowing_system = str(self.tk.call("tk", "windowingsystem"))
        except tkinter.TclError:
            self._windowing_system = ""

    def _configure_window(self):
        self.title("Pepper App")
        self.geometry("1100x580")
        self.after(0, self._maximize_window)
        self.protocol("WM_DELETE_WINDOW", self.close_app)

        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_columnconfigure(2, weight=1)
        self.grid_columnconfigure(3, weight=1)
        self.grid_columnconfigure(4, weight=1)
        self.grid_columnconfigure(5, weight=1)

    def _build_top_controls(self):
        self.ip_entry = customtkinter.CTkEntry(self)
        self.ip_entry.insert(0, "192.168.1.102")
        self.ip_entry.grid(row=0, column=0, padx=20, pady=20, sticky="w")

        self.connect_button = self._create_button(
            self,
            text="Połącz z Robotem",
            font=self.button_font,
            command=self.connect,
        )
        self.connect_button.grid(row=0, column=1, padx=20, pady=20, sticky="w")

        self.id_label = customtkinter.CTkLabel(self, text="ID Pacjenta:")
        self.id_label.grid(row=0, column=2, padx=(20, 5), pady=20, sticky="e")

        self.id_entry = customtkinter.CTkEntry(self, width=150)
        self.id_entry.grid(row=0, column=3, padx=(5, 20), pady=20, sticky="w")

        self.mode_power_frame = customtkinter.CTkFrame(self)
        self.mode_power_frame.grid(row=0, column=4, padx=(0, 20), pady=20, sticky="nsew")
        self.mode_power_frame.grid_columnconfigure(0, weight=1)
        self.mode_power_frame.grid_rowconfigure((0, 1), weight=1)

        self.id_mode_toggle_frame = customtkinter.CTkFrame(self.mode_power_frame)
        self.id_mode_toggle_frame.grid(row=0, column=0, padx=0, pady=(0, 5), sticky="ew")
        self.id_mode_toggle_frame.grid_columnconfigure((0, 1), weight=1, uniform="id_mode_cols")

        control_button = self._create_button(
            self.id_mode_toggle_frame,
            text="GRUPA KONTROLNA",
            width=0,
            height=30,
            font=self.button_font,
            command=lambda: self.select_id_mode("GRUPA KONTROLNA"),
        )
        control_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        experimental_button = self._create_button(
            self.id_mode_toggle_frame,
            text="GRUPA EKSPERYMENTALNA",
            width=0,
            height=30,
            font=self.button_font,
            command=lambda: self.select_id_mode("GRUPA EKSPERYMENTALNA"),
        )
        experimental_button.grid(row=0, column=1, padx=(5, 0), sticky="ew")

        self._id_mode_buttons = {
            "GRUPA KONTROLNA": control_button,
            "GRUPA EKSPERYMENTALNA": experimental_button,
        }
        self._update_id_mode_buttons()

        self.power_button = self._create_button(
            self.mode_power_frame,
            text="Wyłącz",
            width=300,
            height=30,
            font=self.button_font,
            command=self.toggle_power,
        )
        self.power_button.configure(fg_color="#c96100", hover_color="#9f4c00")
        self.power_button.grid(row=1, column=0, padx=0, pady=(5, 0), sticky="ew")

        self.record_toggle_button = self._create_button(
            self,
            text="Record",
            fg_color="green",
            hover_color="#006400",
            width=400,
            height=60,
            font=self.button_font,
            command=self.toggle_recording,
        )
        self.record_toggle_button.grid(row=0, column=5, padx=20, pady=20, sticky="ew")

        self.loading_bar = customtkinter.CTkProgressBar(self, progress_color="#a60d02")
        self.loading_bar.grid(row=1, column=2, columnspan=4, padx=20, pady=10, sticky="ew")

        self.large_textbox = customtkinter.CTkTextbox(self, width=300, height=100, font=self.say_textbox_font)
        self.large_textbox.grid(row=2, column=0, columnspan=2, padx=20, pady=(20, 10), sticky="nsew")
        self._apply_say_textbox_editable_state()
        self.large_textbox.bind("<Return>", self._handle_say_textbox_enter, add="+")
        self.large_textbox.bind("<KP_Enter>", self._handle_say_textbox_enter, add="+")

        self.say_button = self._create_button(
            self,
            text="Say",
            width=120,
            height=40,
            font=self.button_font,
            command=self.say_text,
        )
        self.say_button.grid(row=3, column=0, columnspan=2, padx=20, pady=(0, 20), sticky="ew")
        self.say_button.bind("<Return>", self._handle_say_button_enter, add="+")
        self.say_button.bind("<KP_Enter>", self._handle_say_button_enter, add="+")

        self._set_button_state(self.record_toggle_button, "disabled")
        self._set_button_state(self.say_button, "disabled")
        self._set_button_state(self.power_button, "disabled")

    def _load_button_templates(self):
        self.button_template_path = os.path.join(os.path.dirname(__file__), "button_layout_template.tsv")
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

    def _build_dialogue_layout(self):
        self.dialogue_container = customtkinter.CTkFrame(self)
        self.dialogue_container.grid(row=2, column=2, columnspan=4, padx=20, pady=20, sticky="nsew")
        self.dialogue_container.grid_columnconfigure(0, weight=3, uniform="dialogue_cols")
        self.dialogue_container.grid_columnconfigure(1, weight=2, uniform="dialogue_cols")
        self.dialogue_container.grid_rowconfigure(1, weight=1)
        self.dialogue_container.bind("<Configure>", self._on_dialogue_container_configure)

        toggle_frame = customtkinter.CTkFrame(self.dialogue_container)
        toggle_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")
        toggle_frame.grid_columnconfigure((0, 1), weight=1)

        self.wstep_button = self._create_button(
            toggle_frame,
            text="Wstęp + Zakończenie",
            font=self.button_font,
            command=self.show_start_frame,
        )
        self.wstep_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        self.dylematy_button = self._create_button(
            toggle_frame,
            text="Dylematy",
            font=self.button_font,
            command=self.show_problems_frame,
        )
        self.dylematy_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        self.left_container = customtkinter.CTkFrame(self.dialogue_container)
        self.left_container.grid(row=1, column=0, sticky="nsew", padx=(0, 10), pady=(10, 0))
        self.left_container.grid_rowconfigure(0, weight=1)
        self.left_container.grid_columnconfigure(0, weight=1)

        self.start_frame = customtkinter.CTkScrollableFrame(self.left_container)
        self.start_frame.grid(row=0, column=0, sticky="nsew")
        self._register_scrollable_frame(self.start_frame)
        start_buttons = self.button_definitions.get("start", {}).get("default", [])
        self._populate_button_list(self.start_frame, start_buttons, button_height=self.template_button_height_left)

        self.problems_frame = customtkinter.CTkScrollableFrame(self.left_container)
        self.problems_frame.grid(row=0, column=0, sticky="nsew")
        self._register_scrollable_frame(self.problems_frame)
        self.problems_frame.grid_columnconfigure(0, weight=1)
        self.problems_frame.grid_rowconfigure(1, weight=1)

        self.problem_toggle_container = customtkinter.CTkFrame(self.problems_frame)
        self.problem_toggle_container.grid(row=0, column=0, padx=5, pady=(0, 10), sticky="ew")

        problem_items = list(self.button_definitions.get("problems", {}).items()) or [("1", [])]
        self.problem_toggle_buttons = []
        self.problem_subframes = {}
        self.problem_frame_keys = []

        for index, (frame_key, button_defs) in enumerate(problem_items):
            key_text = str(frame_key)
            toggle_button = self._create_button(
                self.problem_toggle_container,
                text=key_text,
                font=self.button_font,
                command=lambda idx=index: self.show_problem_subframe(idx),
            )
            toggle_button.grid(row=0, column=index, padx=5, sticky="ew")
            self.problem_toggle_container.grid_columnconfigure(index, weight=1)
            self.problem_toggle_buttons.append(toggle_button)

            subframe = customtkinter.CTkFrame(self.problems_frame)
            subframe.grid(row=1, column=0, sticky="nsew")
            self._register_scrollable_frame(subframe)
            self._populate_button_list(subframe, button_defs, button_height=self.template_button_height_left)
            subframe.grid_remove()

            self.problem_subframes[key_text] = subframe
            self.problem_frame_keys.append(key_text)

        self.active_problem_index = 0
        self.show_problem_subframe(self.active_problem_index)
        self.problems_frame.grid_remove()

        self.right_scroll_frame = customtkinter.CTkScrollableFrame(self.dialogue_container, width=200)
        self.right_scroll_frame.grid(row=1, column=1, sticky="nsew", pady=(10, 0))
        self._register_scrollable_frame(self.right_scroll_frame)
        self.right_scroll_frame.grid_columnconfigure(0, weight=1)

        right_items = list(self.button_definitions.get("right", {}).items()) or [("misc", [])]
        for row_index, (group_name, button_defs) in enumerate(right_items):
            group_label = str(group_name)
            if group_label in {"affirmation", "silence", "off_topic", "misc"}:
                group_frame = customtkinter.CTkFrame(self.right_scroll_frame)
            else:
                group_frame = customtkinter.CTkFrame(self.right_scroll_frame, label_text=group_label)
            group_frame.grid(row=row_index, column=0, padx=5, pady=(0, 10), sticky="ew")
            self._populate_button_list(
                group_frame,
                button_defs,
                button_height=self.template_button_height_right,
                wrap_text=False,
            )

    def _bind_global_events(self):
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel)
        self.bind_all("<Button-5>", self._on_mousewheel)

    def _load_button_definitions(self, template_path: str):
        definitions = {"start": {"default": []}, "problems": {}, "right": {}}
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
                        "values": {},
                    }
                    if order_value is not None:
                        entry["order"] = order_value
                    entry["value"] = value
                    items.append(entry)
                    entry_lookup[entry_key] = entry
                elif order_value is not None and entry.get("order") is None:
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

    def _populate_button_list(
        self,
        container,
        button_defs,
        button_height=None,
        *,
        wrap_text=True,
        text_anchor="center",
    ):
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
                item.get("sequence", 0),
            ),
        )

        resolved_height = button_height if button_height is not None else getattr(self, "template_button_height_left", None)

        for row_index, definition in enumerate(sorted_definitions):
            label = definition.get("label", "")
            button_kwargs = {"text": label, "width": 0}
            if resolved_height:
                button_kwargs["height"] = resolved_height
            if self.button_font is not None:
                button_kwargs["font"] = self.button_font

            button = self._create_button(container, **button_kwargs)
            try:
                if getattr(button, "_pepper_anchor_set", False) is False:
                    if text_anchor:
                        button.configure(anchor=text_anchor)
                    button._pepper_anchor_set = True
            except tkinter.TclError:
                button._pepper_anchor_set = True

            button.configure(command=lambda entry=definition, btn=button: self._handle_template_button_click(btn, entry))
            button.grid(row=row_index, column=0, padx=5, pady=5, sticky="ew")
            if not wrap_text:
                setattr(button, "_pepper_disable_wraplength", True)

    def _create_button(self, parent, **kwargs):
        button = customtkinter.CTkButton(parent, **kwargs)
        self._initialize_button_colors(button)
        return button

    def _on_dialogue_container_configure(self, _event):
        self._update_dialogue_column_widths()

    def _update_dialogue_column_widths(self):
        container = getattr(self, "dialogue_container", None)
        if container is None:
            return

        try:
            container_width = container.winfo_width()
        except tkinter.TclError:
            container_width = 0

        if container_width <= 1:
            try:
                container_width = container.winfo_reqwidth()
            except tkinter.TclError:
                container_width = 0

        requested = getattr(self, "_left_content_requested_width", 0) or 0
        min_left = 220
        min_right = 260

        if requested <= 0:
            requested = min_left

        left_width = max(min_left, requested)

        if container_width > 0:
            max_by_ratio = max(min_left, int(container_width * 0.6))
            left_width = min(left_width, max_by_ratio)

            if container_width - left_width < min_right:
                left_width = max(0, container_width - min_right)
                if container_width >= min_left + min_right:
                    left_width = max(left_width, min_left)

            if left_width > container_width:
                left_width = container_width

        left_width = max(0, left_width)

        # IMPORTANT RATIO CONFIGURATION
        container.grid_columnconfigure(0, weight=3, uniform="dialogue_cols")
        container.grid_columnconfigure(1, weight=1, uniform="dialogue_cols")
        container.grid_columnconfigure(0, minsize=left_width)

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

    def _resolve_scroll_canvas_from_event(self, event):
        widget = getattr(event, "widget", None)

        while widget is not None:
            canvas = getattr(widget, "_parent_canvas", None)
            if canvas is not None:
                return canvas

            if hasattr(widget, "yview_scroll"):
                return widget

            widget = getattr(widget, "master", None)

        return None

    def _on_mousewheel(self, event):
        canvas = self._active_scroll_canvas
        if canvas is None:
            canvas = self._resolve_scroll_canvas_from_event(event)
        if canvas is None:
            return

        delta_units = 0
        delta_value = getattr(event, "delta", 0)
        if delta_value:
            direction = -1 if delta_value > 0 else 1
            system = getattr(self, "_windowing_system", "")
            if system == "aqua":
                delta_units = direction
            else:
                magnitude = abs(delta_value)
                steps = int(magnitude // 120)
                if steps == 0:
                    steps = 1
                delta_units = direction * steps
        else:
            event_num = getattr(event, "num", None)
            if event_num == 4:
                delta_units = -1
            elif event_num == 5:
                delta_units = 1

        if delta_units:
            canvas.yview_scroll(int(delta_units), "units")
            return "break"

    def _handle_template_button_click(self, button, entry):
        payload = self._resolve_entry_value(entry)
        self.text_button_event(payload)
        self._pending_template_button = button

    def _mark_template_button_used(self, button):
        if button is None:
            return

        try:
            if not button.winfo_exists():
                return
        except tkinter.TclError:
            return

        button._active_override_colors = (self._used_button_fg_color, self._used_button_hover_color)
        try:
            button.configure(fg_color=self._used_button_fg_color, hover_color=self._used_button_hover_color)
        except tkinter.TclError:
            pass

    def _equalize_left_panel_width(self):
        try:
            self.update_idletasks()
        except tkinter.TclError:
            return

        start_width = 0
        problems_width = 0

        if hasattr(self, "start_frame"):
            try:
                start_width = self.start_frame.winfo_reqwidth()
            except tkinter.TclError:
                start_width = 0

        if hasattr(self, "problems_frame"):
            try:
                problems_width = self.problems_frame.winfo_reqwidth()
            except tkinter.TclError:
                problems_width = 0

        target_width = max(start_width, problems_width)
        if target_width <= 0:
            self._left_content_requested_width = 0
            self._update_dialogue_column_widths()
            return

        self._left_content_requested_width = target_width
        self._update_dialogue_column_widths()

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
        modifiers = getattr(event, "state", 0)
        if modifiers & (1 | 4 | 8):
            return None

        if getattr(self.say_button, "cget", None) and self.say_button.cget("state") == "disabled":
            return "break"

        self.say_text()
        return "break"

    def _handle_say_button_enter(self, _event):
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
