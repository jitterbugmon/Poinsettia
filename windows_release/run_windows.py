from __future__ import annotations

import threading
import webbrowser

from werkzeug.serving import make_server

from poinsettia_windows.desktop_shell import create_shell_app
from poinsettia_windows.ollama import OllamaManager
from poinsettia_windows.site_mirror import load_site_app, prepare_site_copy


def main() -> None:
    site_directory = prepare_site_copy()
    site_app = load_site_app(site_directory)
    site_server = make_server("127.0.0.1", 0, site_app)
    site_url = f"http://127.0.0.1:{site_server.server_port}"
    site_thread = threading.Thread(target=site_server.serve_forever, daemon=True)
    site_thread.start()

    ollama = OllamaManager()
    shell_app = create_shell_app(site_url, ollama)
    shell_server = make_server("127.0.0.1", 0, shell_app)
    shell_url = f"http://127.0.0.1:{shell_server.server_port}"
    shell_thread = threading.Thread(target=shell_server.serve_forever, daemon=True)
    shell_thread.start()
    try:
        import webview

        webview.create_window("Poinsettia", shell_url, fullscreen=True, min_size=(900, 620))
        webview.start()
    except ImportError:
        webbrowser.open(shell_url)
        shell_thread.join()
    finally:
        shell_server.shutdown()
        site_server.shutdown()


if __name__ == "__main__":
    main()