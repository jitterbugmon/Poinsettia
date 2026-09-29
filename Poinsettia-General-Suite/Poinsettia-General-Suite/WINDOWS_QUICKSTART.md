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

## Update an existing ZIP copy

The ZIP launcher does **not** update application code automatically. To get new
features such as Poinsettia 2 web search and downloadable files:

1. Close Poinsettia and the launcher window. Do not update files while the app
   is running; an already-running server on port 5000 will keep serving old code.
2. Make a backup of your entire extracted Poinsettia folder. In particular,
   `poinsettia.db` contains your accounts and chats, and `user_files` contains
   generated files. Keep the backup until the update works.
3. If Windows shows **Unblock** in the downloaded update ZIP's **Properties**,
   select it before extraction. Extract the **Poinsettia Windows ZIP code
   update** into that same folder, replacing code files when Windows asks. Do
   not extract it into a second, nested Poinsettia folder. The code update
   contains neither `poinsettia.db` nor `user_files`, so it does not replace
   those data files.
4. Double-click `start_poinsettia.bat` again. Refresh the chat page, select
   Poinsettia 2, and ask a factual question. Search status should appear while
   it retrieves results; source links appear under answers when pages are found.

If Poinsettia still answers without sources, check `poinsettia-error.log` in
`%LOCALAPPDATA%\Poinsettia\Bootstrap\`. A `Poinsettia 2.9 search_duration_ms`
line shows that the new code ran; zero sources means it found no citable page
URLs for that question. Nearby DuckDuckGo or Wikipedia warnings can explain
whether a provider returned an empty page or failed.

Search prefers sources suited to the question, including IMDb for films,
Adafruit and Hacker News for technology, and Amazon for shopping. Reddit is
eligible for discussions. These sites are not guaranteed to appear for every
query. Some sites block automated page requests; in that case a result may be
marked **Search-result snippet (full page unavailable)**. That text is from
the search index, not a verified reading of the linked page.

Poinsettia 2.9 uses the multimodal `gemma4:e4b` base. An updated ZIP copy
recreates its `poinsettia` model from this base when you relaunch
`start_poinsettia.bat`. The E4B download is about 9.6 GB and requires a
compatible, up-to-date Ollama installation. Images and WAV audio are sent
directly to P2, not through P3. If an attachment still fails, check
`%LOCALAPPDATA%\Poinsettia\Bootstrap\poinsettia-error.log` for the model error.

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

### "Did not find executable" while installing Python requirements

An older `.poinsettia-venv` folder may still point to a Python installation
that was removed or moved. The updated launcher detects this and rebuilds that
generated environment before installing requirements.

If you are running an older ZIP copy, close the launcher, delete **only**
`.poinsettia-venv` from the extracted folder beside `start_poinsettia.bat`,
then run the batch file again. Python packages will be reinstalled. This does
not delete your chats, generated files, or Ollama models.

Poinsettia 4.0 Fax and Candor are available immediately. The first run
prepares both P4 models along with P2 and P3.