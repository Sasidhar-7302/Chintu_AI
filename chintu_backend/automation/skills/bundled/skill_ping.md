# ping
Description: Network reachability check using ping (Windows syntax). Use with args=...
Triggers: ping args=, ping host args=
Command: ping -n 4 {args}
Args: args
Type: shell
Requires-Bin: ping
