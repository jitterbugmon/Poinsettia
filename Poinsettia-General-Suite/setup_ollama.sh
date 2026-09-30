
#!/bin/bash

echo "Setting up Poinsettia 2 with Ollama..."

OLLAMA_BIN="${OLLAMA_BIN:-/home/runner/workspace/.ollama-runtime/bin/ollama}"
if [ ! -x "$OLLAMA_BIN" ]; then
    OLLAMA_BIN="$(command -v ollama || true)"
fi

# Check if ollama is installed
if [ -z "$OLLAMA_BIN" ] || [ ! -x "$OLLAMA_BIN" ]
then
    echo "Ollama is not installed. Installing..."
    curl -fsSL https://ollama.com/install.sh | sh
    OLLAMA_BIN="$(command -v ollama)"
fi

if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "Starting Ollama server..."
    "$OLLAMA_BIN" serve >/tmp/poinsettia-ollama.log 2>&1 &
    sleep 3
fi

echo "Downloading the base model if needed..."
"$OLLAMA_BIN" pull llama3.2:3b
"$OLLAMA_BIN" pull gemma4:12b
"$OLLAMA_BIN" pull gemma4:26b
"$OLLAMA_BIN" pull gemma4:31b

echo "Creating Poinsettia model..."
"$OLLAMA_BIN" create poinsettia -f Modelfile
echo "Creating Poinsettia 3 model..."
"$OLLAMA_BIN" create p3 -f modelfile3
echo "Creating Poinsettia 4.0 Fax model..."
"$OLLAMA_BIN" create p4-fax -f modelfile4-fax
echo "Creating Poinsettia 4.0 Candor model..."
"$OLLAMA_BIN" create p4-candor -f modelfile4-candor

echo "Setup complete! Poinsettia 2.9, Poinsettia 3.9, and the Poinsettia 4.0 models are ready to use."
