# Poinsettia

## Overview
Poinsettia is a lightweight AI-powered assistant using Ollama for streaming responses. Clean, minimal codebase ready for migration to VS Code or other environments.

## Approved browser architecture
The user chose the following target on 2026-09-30:
- No companion application, native installer, Python installation, or Ollama installation on the visitor's computer.
- The cloud Poinsettia server serves the website and supporting services, including web retrieval, accounts, conversations, and files.
- Model inference runs in the visitor's browser through WebGPU, not on the cloud support server.
- Preserve the existing P2/P3/P4 user-facing functionality, including sources, weather, attachments, streaming, downloadable files, and the workspace.
- Do not silently substitute smaller models, drop modes, or fall back to cloud inference. Browser model compatibility and device limits must be verified and clearly reported.

This is the approved target, not the current implemented runtime. The existing app still invokes Ollama. The install-first page in `docs/` is an earlier prototype and must not be published as the new browser experience.

The separately requested `poinsettia-installation-site/` is a static capabilities/download website for GitHub Pages. It has no application backend and does not change the no-companion architecture of the chat app.

## Project Structure
- `main.py` - Minimal Flask backend (~100 lines)
- `templates/home.html` - Landing page
- `templates/index.html` - Chat interface with streaming support
- `attached_assets/` - Logo images

## Features
- **Ollama Integration** - Streams responses from local "poinsettia" model
- **Real-time Streaming** - Watch responses generate with cursor animation
- **Landing Page** - About Us, Mission, and Features sections
- **Version History** - Track changes in the app
- **Mobile Responsive** - Works on all screen sizes

## Running the App
The Flask app runs on port 5000.

## API Endpoints
- `GET /` - Landing page
- `GET /chat` - Chat interface
- `POST /chat/stream` - Streaming chat endpoint

## Dependencies
Minimal dependencies for easy migration:
- Flask
- requests

## Recent Changes (Dec 2025)
- v2.0.0: Deprecated Poinsettia 1, removed all legacy code
- Streamlined from 700+ lines to ~100 lines
- Removed: NLTK, BeautifulSoup, numpy, web scraping
- Single Ollama-powered endpoint

## Architecture
- Backend: Flask (Python)
- Frontend: HTML/CSS/JavaScript with Server-Sent Events
- AI: Ollama local LLM integration
