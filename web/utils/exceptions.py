class InvalidHash(Exception):
    def __init__(self, message: str = "Invalid hash"):
        self.message = message
        super().__init__(self.message)

class FileNotFound(Exception):
    def __init__(self, message: str = "File not found"):
        self.message = message
        super().__init__(self.message)
