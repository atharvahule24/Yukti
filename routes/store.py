from collections.abc import MutableMapping
from typing import Iterator

from db import delete_session_data, get_session_data, list_session_data, save_session_data


class SQLiteSessionStore(MutableMapping):
    def __getitem__(self, key: str):
        data = get_session_data(key)
        if data is None:
            raise KeyError(key)
        return data

    def __setitem__(self, key: str, value):
        save_session_data(key, value)

    def __delitem__(self, key: str):
        if get_session_data(key) is None:
            raise KeyError(key)
        delete_session_data(key)

    def __iter__(self) -> Iterator[str]:
        return (session["id"] for session in list_session_data())

    def __len__(self) -> int:
        return len(list_session_data())

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and get_session_data(key) is not None

    def items(self):
        return [(session["id"], session) for session in list_session_data()]


session_store = SQLiteSessionStore()
