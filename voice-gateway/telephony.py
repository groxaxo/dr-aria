"""PCMA/PCMU codec utilities and WAV builder for telephony audio."""
import audioop
import struct


TELNYX_SAMPLE_RATE = 8000
TELNYX_FRAME_MS = 20
TELNYX_FRAME_SAMPLES = int(TELNYX_SAMPLE_RATE * TELNYX_FRAME_MS / 1000)  # 160


def pcma_to_pcm16(data: bytes) -> bytes:
    """Decode PCMA (G.711 a-law) to signed 16-bit PCM little-endian."""
    return audioop.alaw2lin(data, 2)


def pcm16_to_pcma(data: bytes) -> bytes:
    """Encode signed 16-bit PCM little-endian to PCMA (G.711 a-law)."""
    return audioop.lin2alaw(data, 2)


def pcmu_to_pcm16(data: bytes) -> bytes:
    """Decode PCMU (G.711 mu-law) to signed 16-bit PCM little-endian."""
    return audioop.ulaw2lin(data, 2)


def pcm16_to_pcmu(data: bytes) -> bytes:
    """Encode signed 16-bit PCM little-endian to PCMU (G.711 mu-law)."""
    return audioop.lin2ulaw(data, 2)


def build_wav(pcm16_data: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Wrap raw PCM16-LE data in a WAV file header."""
    bits_per_sample = 16
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    data_size = len(pcm16_data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,            # chunk size
        1,             # PCM format
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )
    return header + pcm16_data


def resample_8k_to_16k(pcm16_data: bytes) -> bytes:
    """Upsample 8kHz PCM16 to 16kHz PCM16 via simple linear interpolation."""
    # audioop.ratecv: from_rate, to_rate, nchannels, sample_width, state, weightA, weightB
    result, _ = audioop.ratecv(pcm16_data, 2, 1, TELNYX_SAMPLE_RATE, 16000, None)
    return result


def pcma_frames_to_wav_16k(pcma_chunks: list[bytes]) -> bytes:
    """Convert a list of PCMA chunks to a 16kHz WAV for ASR."""
    raw_pcm8k = b"".join(pcma_to_pcm16(chunk) for chunk in pcma_chunks)
    pcm16k = resample_8k_to_16k(raw_pcm8k)
    return build_wav(pcm16k, sample_rate=16000, channels=1)


def chunk_pcma_for_telnyx(pcma_data: bytes, frame_bytes: int = TELNYX_FRAME_SAMPLES) -> list[bytes]:
    """Split PCMA audio into Telnyx-sized frames (default 160 bytes = 20ms at 8kHz)."""
    chunks = []
    for offset in range(0, len(pcma_data), frame_bytes):
        chunk = pcma_data[offset : offset + frame_bytes]
        if len(chunk) == frame_bytes:
            chunks.append(chunk)
    return chunks


def average_abs_amplitude(pcm16_data: bytes) -> float:
    """Compute mean absolute amplitude of PCM16 data (0–32767)."""
    if not pcm16_data:
        return 0.0
    total = sum(abs(audioop.getsample(pcm16_data, 2, i)) for i in range(len(pcm16_data) // 2))
    return total / (len(pcm16_data) // 2)
