"""Entry point. Runs the app; if it fails to start, shows the error on screen instead of closing."""
import traceback


def run_crash_screen(tb):
    from kivy.app import App
    from kivy.core.clipboard import Clipboard
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.scrollview import ScrollView

    class CrashApp(App):
        def build(self):
            root = BoxLayout(orientation="vertical", padding=10, spacing=8)
            root.add_widget(Label(text="Startup error - please send a screenshot",
                                  size_hint_y=None, height=40, color=(1, 0.4, 0.4, 1)))
            sv = ScrollView()
            lbl = Label(text=tb, font_size="12sp", size_hint_y=None, halign="left", valign="top")
            lbl.bind(width=lambda *_: setattr(lbl, "text_size", (lbl.width, None)))
            lbl.bind(texture_size=lambda *_: setattr(lbl, "height", lbl.texture_size[1]))
            sv.add_widget(lbl)
            root.add_widget(sv)
            btn = Button(text="Copy error", size_hint_y=None, height=48)
            btn.bind(on_release=lambda *_: Clipboard.copy(tb))
            root.add_widget(btn)
            return root

    CrashApp().run()


try:
    import app_main
    app_main.KhalilDownloaderApp().run()
except Exception:
    run_crash_screen(traceback.format_exc())
