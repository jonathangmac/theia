"""Embedding gate — skip VLM analysis when the scene hasn't visually changed.

Uses perceptual hashing (pHash) for a zero-cost, local comparison. This avoids
unnecessary VLM API calls when consecutive frames are visually similar (e.g.
a quiet street with no movement).
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


def compute_phash(image_path, hash_size: int = 16) -> int:
    """Compute a perceptual hash of an image.

    Resizes to hash_size x hash_size, converts to grayscale, then compares
    each pixel to the mean. Returns a hash as an integer.
    """
    img = Image.open(image_path).convert("L").resize(
        (hash_size, hash_size), Image.LANCZOS
    )
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for i, px in enumerate(pixels):
        if px > avg:
            bits |= 1 << i
    return bits


def hamming_distance(hash_a: int, hash_b: int) -> int:
    """Count the number of differing bits between two hashes."""
    return bin(hash_a ^ hash_b).count("1")


@dataclass
class GateDecision:
    should_process: bool
    distance: int
    reason: str


class EmbeddingGate:
    """Decides whether a frame is different enough to warrant VLM analysis.

    Compares the current frame's perceptual hash to the last processed frame.
    If the Hamming distance is below the threshold, the scene hasn't changed
    enough and the VLM call can be skipped.
    """

    def __init__(self, threshold: int = 15, hash_size: int = 16):
        self.threshold = threshold
        self.hash_size = hash_size
        self.last_hash: int | None = None
        self.skipped_count: int = 0
        self.processed_count: int = 0

    def should_process(self, image_path) -> GateDecision:
        """Returns whether this frame should be sent to the VLM."""
        current_hash = compute_phash(image_path, self.hash_size)

        if self.last_hash is None:
            self.last_hash = current_hash
            self.processed_count += 1
            return GateDecision(True, 0, "First frame — establishing baseline")

        distance = hamming_distance(self.last_hash, current_hash)

        if distance < self.threshold:
            self.skipped_count += 1
            return GateDecision(False, distance, f"Scene unchanged (distance={distance})")

        self.last_hash = current_hash
        self.processed_count += 1
        return GateDecision(True, distance, f"Scene changed (distance={distance})")

    def stats(self) -> dict:
        total = self.skipped_count + self.processed_count
        skip_rate = (self.skipped_count / total * 100) if total > 0 else 0
        return {
            "processed": self.processed_count,
            "skipped": self.skipped_count,
            "skip_rate": f"{skip_rate:.1f}%",
        }
