class Server:
    def __init__(self, port: int = 8000) -> None:
        self.port = port
        self.running = False

    def run(self) -> None:
        self.running = True
        print(f"Server running on port {self.port}")


def start_server(port: int = 8000) -> Server:
    server = Server(port=port)
    server.run()
    return server
