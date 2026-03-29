"""A simple hello world module."""
MESSAGE = "Hello, World!"

def greet(name: str) -> str:
    return f"Hello, {name}!"

class Greeter:
    def __init__(self, prefix: str = "Hi"):
        self.prefix = prefix

    def say(self, name: str) -> str:
        return f"{self.prefix}, {name}!"
