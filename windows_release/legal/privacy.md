# Poinsettia Windows Privacy Policy

**Version:** windows-1.3
**Effective date:** October 14, 2026

Poinsettia Windows is designed for local use. Account records and the signed-in
website database are not used by this separate desktop release.

## Information stored locally

The application stores a DPAPI-protected install key and a signed consent
record under the current Windows user's local application-data directory. The
consent record contains the accepted agreement version, agreement digest, and
timestamp. Chat prompts, attached images, and imported or recorded speech/audio
are sent to the local Ollama service selected by the application. Poinsettia 4.0
accepts image uploads but does not provide audio import or microphone controls.
The desktop release does not save raw image or audio bytes as conversation
messages.

## Network requests

The first-run setup may contact the official Ollama download endpoint and the
local Ollama API. Web search and cited article content use Wikipedia only.
Weather requests may contact the National Weather Service, and location lookup
may contact OpenStreetMap's Nominatim service. Do not submit sensitive
information to any external source.

## Choices

You may stop using the application and remove its local application-data
directory. Removing consent state will cause the clickwrap gate to appear
again. Removing model files can require a new download.

## Changes

This policy may change with the Windows release. A newer version will be shown
before protected chat is enabled.