# Nexora Python SDK foundation

The SDK is an in-process facade over policy-checked Nexora services. It never executes package code, shell commands, Docker operations, or production actions. Instantiate `NexoraSDK` with an authenticated actor namespace and an authorized workspace, then use `create_agent`, `create_team`, or `create_plan`.
