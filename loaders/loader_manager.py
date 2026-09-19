from loaders.file_loader import FileLoader
from loaders.youtube_loader import YoutubeLoader

class LoaderManager:

    def load(self, input_value):

        if input_value.startswith("http"):
            return YoutubeLoader(input_value).load()
        else:
            return FileLoader(input_value).load()
