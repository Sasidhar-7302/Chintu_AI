# MCP Docker Sandbox

This project ships a minimal MCP server for Docker sandboxing and a matching client.
The server runs over stdio and exposes docker_run/docker_exec/docker_start/docker_stop.

Quick start
1) Build the sandbox image (optional):
   docker build -t chintu-sandbox:latest docker/sandbox
2) Start the MCP server:
   python -m chintu_backend.mcp.docker_server
3) Enable MCP in `.env` (optional):
   CHINTU_MCP_DOCKER_ENABLED=true
   CHINTU_MCP_DOCKER_COMMAND=python
   CHINTU_MCP_DOCKER_ARGS=["-m","chintu_backend.mcp.docker_server"]
   CHINTU_DOCKER_SANDBOX_IMAGE=chintu-sandbox:latest

Docker Desktop on Windows
- Ensure Docker Desktop is running with the WSL2 backend.
- The MCP server uses the Docker CLI, which is already wired to the local engine.
