# docker
Description: Run Docker commands. Use with args=...
Triggers: docker args=, docker command args=
Command: docker {args}
Args: args
Type: shell
Requires-Bin: docker
