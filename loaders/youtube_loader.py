from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
from langchain_core.documents import Document
from loaders.base_loader import BaseLoader


class YoutubeLoader(BaseLoader):

    def extract_video_id(self, url: str) -> str:
        parsed_url = urlparse(url)

        if parsed_url.hostname in ["www.youtube.com", "youtube.com"]:
            query_params = parse_qs(parsed_url.query)
            if "v" in query_params:
                return query_params["v"][0]

        if parsed_url.hostname == "youtu.be":
            return parsed_url.path.lstrip("/")

        if "embed" in parsed_url.path:
            return parsed_url.path.split("/")[-1]

        raise ValueError("Invalid YouTube URL")

    def load(self):
        # 1. Extract ID
        video_id = self.extract_video_id(self.file_path)

        # 2. Fetch transcript
        ytt_api = YouTubeTranscriptApi()
        fetched_transcript = ytt_api.fetch(video_id)

        transcript = " ".join(snippet.text for snippet in fetched_transcript)

        return [
            Document(
                page_content=transcript,
                metadata={"source": self.file_path}
            )
        ]
