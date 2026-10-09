"""Start llama.cpp's llama-server on demand, locally or on a remote host over ssh, and stop it when idle.

A server this tool did not start is reused but never stopped.
"""
from .client import ChatResult, ClientError, ContextTooLarge, LlamaClient
from .manager import LlamaManager, LlamaRefused, LlamaUnavailable

__all__ = ["ChatResult", "ClientError", "ContextTooLarge", "LlamaClient", "LlamaManager", "LlamaRefused",
           "LlamaUnavailable"]
__version__ = "0.1.0"
