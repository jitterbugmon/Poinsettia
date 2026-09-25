# Poinsettia

## Overview
Poinsettia is a lightweight AI-powered assistant using Ollama for streaming responses. Clean, minimal codebase ready for migration to VS Code or other environments.

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
