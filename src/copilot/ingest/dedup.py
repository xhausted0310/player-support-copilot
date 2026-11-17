"""Near-duplicate detection with MinHash + LSH over word shingles."""

import re

from datasketch import MinHash, MinHashLSH

_WORD = re.compile(r"\w+", re.UNICODE)


def shingles(text: str, n: int) -> set[str]:
    words = _WORD.findall(text.lower())
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def minhash(text: str, *, num_perm: int, shingle_words: int) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for s in shingles(text, shingle_words):
        m.update(s.encode("utf-8"))
    return m


class NearDuplicateIndex:
    """Insert documents one by one; `find_duplicate` returns the key of a similar one, if any."""

    def __init__(self, *, threshold: float, num_perm: int, shingle_words: int) -> None:
        self._lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._hashes: dict[str, MinHash] = {}
        self._num_perm = num_perm
        self._shingle_words = shingle_words
        self._threshold = threshold

    def __len__(self) -> int:
        return len(self._hashes)

    def __contains__(self, key: str) -> bool:
        return key in self._hashes

    def find_duplicate(self, text: str, *, exclude: str | None = None) -> str | None:
        m = minhash(text, num_perm=self._num_perm, shingle_words=self._shingle_words)
        candidates: list[str] = [k for k in self._lsh.query(m) if k != exclude]
        # LSH is probabilistic: confirm candidates with the estimated Jaccard similarity.
        best = max(candidates, key=lambda k: m.jaccard(self._hashes[k]), default=None)
        if best is not None and m.jaccard(self._hashes[best]) >= self._threshold:
            return best
        return None

    def add(self, key: str, text: str) -> None:
        if key in self._hashes:
            self._lsh.remove(key)
        m = minhash(text, num_perm=self._num_perm, shingle_words=self._shingle_words)
        self._lsh.insert(key, m)
        self._hashes[key] = m
