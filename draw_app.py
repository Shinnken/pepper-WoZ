import tkinter as tk
import customtkinter as ctk

# Set appearance mode and color theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class DrawApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Osoba zaczynająca")
        self.geometry("1000x960")
        self.resizable(False, False)

        self.loading = False
        self.loading_angle = 0
        self.loading_job = None
        self.finish_job = None

        # Label for the drawn option
        self.text_label = ctk.CTkLabel(self, text="Rozmowę zaczyna:", font=("Arial", 40))
        self.text_label.pack(pady=220)
        self.result_label = ctk.CTkLabel(self, text="", font=("Arial", 48, "bold"))
        self.result_label.pack(pady=25)

        # Canvas hosted loading animation to build suspense; use native Tk canvas for macOS compatibility
# NEW
        self.loading_canvas = ctk.CTkCanvas(self, width=90, height=90, highlightthickness=0, bd=0, relief="flat")
        self._apply_canvas_colors()
        self.loading_canvas.pack(pady=5)
        self.loading_canvas.pack_forget()

        # Draw button
        self.draw_button = ctk.CTkButton(self, text="LOSUJ", command=self.draw_option, font=("Arial", 18))
        self.draw_button.pack(pady=10)

    def draw_option(self):
        if self.loading:
            return
        self.result_label.configure(text="")
        self.draw_button.configure(state="disabled")
        self.loading_canvas.pack(pady=5)
        self.loading = True
        self.animate_loading()
        if self.finish_job is not None:
            self.after_cancel(self.finish_job)
            self.finish_job = None
        self.finish_job = self.after(2000, self.finish_draw)

    def animate_loading(self):
        if not self.loading:
            return
        self.loading_canvas.delete("all")
        self._apply_canvas_colors()
        outline_color = self._color_for_mode("#bbbbbb", "#5f6368")
        highlight_color = self._color_for_mode("#1a73e8", "#8ab4f8")
        self.loading_canvas.create_oval(20, 20, 70, 70, outline=outline_color, width=3)
        self.loading_canvas.create_arc(
            20,
            20,
            70,
            70,
            start=self.loading_angle,
            extent=270,
            style="arc",
            outline=highlight_color,
            width=5,
        )
        self.loading_angle = (self.loading_angle + 15) % 360
        self.loading_job = self.after(80, self.animate_loading)

    def finish_draw(self):
        self.loading = False
        if self.loading_job is not None:
            self.after_cancel(self.loading_job)
            self.loading_job = None
        self.loading_canvas.delete("all")
        self.loading_canvas.pack_forget()
        self.result_label.configure(text="ROBOT")
        self.draw_button.configure(state="normal")
        self.finish_job = None

    def _color_for_mode(self, light_color: str, dark_color: str) -> str:
        appearance = ctk.get_appearance_mode()
        return light_color if appearance == "Light" else dark_color

    def _apply_canvas_colors(self) -> None:
        background = self._color_for_mode("#f5f5f5", "#242424")
        # Use 'bg_color' for customtkinter widgets
        self.loading_canvas.configure(background=background)

if __name__ == "__main__":
    app = DrawApp()
    app.mainloop()
