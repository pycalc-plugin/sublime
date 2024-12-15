import os
import sys
from code import InteractiveConsole
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from queue import Empty, Queue
from threading import Thread

import sublime
import sublime_plugin

thread = None
queue_input = Queue()
queue_output = Queue(maxsize=256)
print_result_running = False


def get_plugin_path():
    path = os.path.join(sublime.packages_path(), __package__)
    if not os.path.isdir(path):
        os.makedirs(path)

    return path


def get_settings_path():
    return "pycalc.sublime-settings"


def is_enabled():
    settings = sublime.load_settings(get_settings_path())
    return settings.get("enabled", True)


def set_enabled(enabled: bool):
    settings = sublime.load_settings(get_settings_path())
    settings.set("enabled", enabled)
    sublime.save_settings(get_settings_path())


def store_context_menu():
    caption = "pycalc [✓]" if is_enabled() else "pycalc [×]"
    menu = [
        {"id": "pycalc", "command": "pycalc_toggle", "caption": caption},
        {
            "id": "pycalc",
            "command": "pycalc_selected",
            "caption": "pycalc selected",
        },
    ]

    menu_path = os.path.join(get_plugin_path(), "Context.sublime-menu")
    with open(menu_path, "w", encoding="utf-8") as f:
        f.write(sublime.encode_value(menu, True))


def interact(repl, line):
    if not line:
        return {}

    stdout = StringIO()
    stderr = StringIO()

    multiline, line = line[0], line[1:]
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            if multiline == "1":
                repl.resetbuffer()
                repl.runcode(line)
            else:
                repl.push(line)
        except BaseException as e:
            sys.stderr.write(repr(e))

    buffer = stdout.getvalue()
    if buffer == f"{line.strip()}\n":
        buffer = ""

    return {"stdout": buffer, "stderr": stderr.getvalue()}


def worker(queue_in: Queue, queue_out: Queue):
    help_func = """
def __help__():
    print('''Welcome to Python 3.8's help utility!

If this is your first time using Python, you should definitely check out
the tutorial on the internet at https://docs.python.org/3.8/tutorial/.''')

help = __help__
    """

    repl = InteractiveConsole()
    repl.runcode(help_func)

    while True:
        try:
            line = queue_in.get(timeout=3)
            result = interact(repl, line)
            queue_out.put(result)
        except Empty:
            queue_out.put({})
        except Exception:
            queue_out.put({})


def init_worker():
    global thread
    if thread:
        return

    thread = Thread(target=worker, args=(queue_input, queue_output))
    thread.daemon = True
    thread.start()


def execute_python_code(code: str, multiline: bool):
    if multiline:
        code = "1" + code
    else:
        code = "0" + code

    queue_input.put(code)


def init_print_result():
    global print_result_running
    if print_result_running:
        return

    print_result_running = True
    sublime.set_timeout_async(print_result, 10)


def print_result():
    queue_count = 0
    try:
        result = queue_output.get(timeout=30)
        queue_count += 1
        if not result:
            sublime.set_timeout_async(print_result, 10)
            return

        stdout = result.get("stdout", None)
        if stdout:
            window = sublime.active_window()
            view = window.active_view()
            view.run_command("insert", {"characters": stdout})

        stderr = result.get("stderr", None)
        show_info(stderr)

        sublime.set_timeout_async(print_result, 10)
    except Empty:
        if queue_count != 0:
            sublime.set_timeout_async(print_result, 10)
            return

        result = sublime.ok_cancel_dialog(
            msg="The Python code has been running for a long time. Do you want to terminate it?",
            ok_title="Yes",
        )
        if result:
            sys.exit()
        else:
            sublime.set_timeout_async(print_result, 10)


def show_info(message: str):
    if not message:
        return

    window = sublime.active_window()

    panel = window.get_output_panel("pycalc")
    panel.run_command("append", {"characters": message})

    args = {"panel": "output.pycalc"}
    window.run_command("show_panel", args)
    sublime.set_timeout(lambda: window.run_command("hide_panel", args), 7000)


class PycalcCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        try:
            init_worker()
            init_print_result()

            if not is_enabled():
                return

            sel = self.view.sel()[0]
            region = self.view.line(sel)
            line = self.view.substr(region)

            line = line[: sel.begin() - region.begin()]
            execute_python_code(line, False)
        finally:
            self.view.run_command("insert", {"characters": "\n"})
            sublime.set_timeout_async(print_result, 10)


class PycalcSelectedCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        code = ""
        try:
            init_worker()
            init_print_result()

            sel = self.view.sel()[0]
            region = self.view.line(sel)
            code = self.view.substr(region)

            self.view.sel().clear()
            self.view.sel().add(sublime.Region(region.end()))

            execute_python_code(code, True)
        finally:
            if not code.endswith("\n"):
                self.view.run_command("insert", {"characters": "\n"})
            sublime.set_timeout_async(print_result, 10)


class PycalcToggleCommand(sublime_plugin.ApplicationCommand):
    def run(self):
        set_enabled(not is_enabled())
        store_context_menu()


store_context_menu()
