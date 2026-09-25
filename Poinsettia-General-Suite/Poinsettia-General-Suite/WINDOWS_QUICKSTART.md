# Poinsettia Windows quick start

## Recommended: install with one click

Download the signed `Poinsettia-<version>-Windows-x64-Setup.exe` installer from
the official release and run it. It:

- installs for the current user without requiring administrator access;
- creates a Start Menu shortcut and optional Desktop shortcut;
- launches Poinsettia after installation;
- installs Ollama automatically when needed;
- shows first-run consent and setup progress; and
- downloads and prepares the Poinsettia models through the app.

After installation, launch **Poinsettia** from the Start Menu. No terminal
commands are required.

The first model setup can take a long time because the model downloads are
large. Keep the app open while setup completes.

## ZIP fallback for development

The project ZIP is a development fallback, not the recommended customer
distribution. If you are using it:

1. Right-click the ZIP, choose **Properties**, check **Unblock** if shown, and
   click **Apply**.
2. Extract it to a writable folder, such as `Documents\Poinsettia`.
3. Double-click `start_poinsettia.bat`.

The batch launcher will find or install Python, create its virtual environment,
install requirements, prepare Ollama and the models, start Flask on
`http://127.0.0.1:5000`, and open the site.

## Later runs with the ZIP fallback

Double-click `start_poinsettia.bat` again. Existing Python packages, Ollama,
and models are reused; model preparation is safe to repeat.

## Troubleshooting

### Windows blocks the batch file

Do not disable Smart App Control globally. First, remove the internet
download marker from the extracted files using PowerShell:

```powershell
cd "C:\path\to\Poinsettia"
Get-ChildItem -Recurse -File | Unblock-File
.\start_poinsettia.bat
```

For a new extraction, it is better to unblock the ZIP in **Properties**
before extracting it. If the dialog specifically says **Smart App Control**
and still blocks the launcher after this step, Windows is refusing the
unsigned ZIP rather than showing a per-file confirmation. In that case, use
the signed Windows installer from the official release when available; do not
turn off Smart App Control just for this download.

Bootstrap logs are stored at:

```text
%LOCALAPPDATA%\Poinsettia\Bootstrap\
```

The most useful files are:

- `poinsettia.log`
- `poinsettia-error.log`
- `ollama.log`
- `ollama-error.log`

Poinsettia 4.0 Fax and Candor are available immediately. The first run
prepares both P4 models along with P2 and P3.