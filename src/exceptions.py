class ProcessMessageError(Exception):
    def __init__(self, message=None, *args, **kwargs):
        self.message = message
        super().__init__()
