class BaseLoader:
    def __init__(self, file_path):
        self.file_path = file_path

    def load(self):
        raise NotImplementedError("Load method must be implemented.")
