"""RFC 8032 Ed25519, pure Python and dependency free.

Signing is deterministic. Verification rejects non-canonical scalars and
failed point decodings. Constant-time scalar multiplication is not a goal
here; correctness and determinism are.
"""
from __future__ import annotations

import hashlib
import secrets

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = (-121665 * pow(121666, P - 2, P)) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)
IDENTITY = (0, 1, 1, 0)


def _recover_x(y: int, sign: int) -> int | None:
    """Return the x coordinate for the point with this y and sign bit.

    None means the bytes are not a point: y outside the field, or y not on the
    curve. x == 0 has one square root, so sign 1 there is rejected rather than
    silently flipped to the only candidate. Callers treat None as a failed
    decoding, never as a value to keep going with.
    """
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    if x2 == 0:
        return 0 if sign == 0 else None
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


def _base_point() -> tuple[int, int, int, int]:
    """Derive the RFC 8032 base point, in extended coordinates.

    y = 4/5 fixes the point and the even square root fixes x, so the result is a
    constant. A ValueError here can only mean the field constants are wrong; it
    is not a data-dependent failure.
    """
    y = 4 * pow(5, P - 2, P) % P
    x = _recover_x(y, 0)
    if x is None:
        raise ValueError("cannot derive the Ed25519 base point")
    return (x, y, 1, x * y % P)


BASE = _base_point()


def _add(first, second):
    """Add two points in extended twisted-Edwards coordinates.

    Arguments and result are (x, y, z, t) with x = X/Z, y = Y/Z, t = XY/Z. The
    formula is the unified one for a = -1, so it handles equal inputs and the
    identity too, which is what lets _multiply use it for every bit.
    """
    x1, y1, z1, t1 = first
    x2, y2, z2, t2 = second
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = 2 * D * t1 * t2 % P
    d = 2 * z1 * z2 % P
    e = b - a
    f = d - c
    g = d + c
    h = b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _double(point):
    """Double a point in extended coordinates.

    The t coordinate is recomputed rather than read, so the fourth element of the
    input cannot influence the result.
    """
    x1, y1, z1, _ = point
    a = x1 * x1 % P
    b = y1 * y1 % P
    c = 2 * z1 * z1 % P
    h = a + b
    e = h - (x1 + y1) * (x1 + y1)
    g = a - b
    f = c + g
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _multiply(scalar: int, point):
    """Return scalar * point by right-to-left double-and-add.

    The loop runs once per bit of the scalar and branches on each bit, so it is
    not constant time; this module trades side-channel resistance for a small,
    dependency-free implementation. A scalar of zero or less returns the
    identity, because the loop never runs.
    """
    result = IDENTITY
    addend = point
    while scalar > 0:
        if scalar & 1:
            result = _add(result, addend)
        addend = _double(addend)
        scalar >>= 1
    return result


def _encode(point) -> bytes:
    """Encode a point as the 32-byte RFC 8032 form.

    z is inverted first, so any projective representative of a point encodes to
    the same bytes. The low bit of x becomes the top bit of the last byte, which
    is where the decoder looks for the sign.
    """
    x, y, z, _ = point
    inverse = pow(z, P - 2, P)
    x = x * inverse % P
    y = y * inverse % P
    data = bytearray(y.to_bytes(32, "little"))
    data[31] |= (x & 1) << 7
    return bytes(data)


def _decode(data: bytes):
    """Decode 32 bytes into extended coordinates, or None.

    Rejects a wrong length, a y outside the field, and a y not on the curve, so a
    malformed signature cannot be coerced onto a nearby point. None is a
    verification failure, not an error: verify turns it into 'the signature does
    not verify'.
    """
    if len(data) != 32:
        return None
    value = int.from_bytes(data, "little")
    sign = value >> 255
    y = value & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def _check_bytes(value, length: int, what: str) -> bytes:
    """Return value as immutable bytes, requiring exactly this length.

    bytearray is accepted and copied, so a caller cannot keep a handle that
    changes the seed or key after it was checked. The ValueError message names
    the argument, which is how a caller with several byte arguments learns which
    one was wrong.
    """
    if not isinstance(value, (bytes, bytearray)):
        raise ValueError(f"{what} must be bytes")
    data = bytes(value)
    if len(data) != length:
        raise ValueError(f"{what} must be {length} bytes")
    return data


def generate_seed() -> bytes:
    """Return 32 fresh random bytes suitable as an Ed25519 seed."""
    return secrets.token_bytes(32)


def public_key(seed: bytes) -> bytes:
    """Derive the 32-byte public key for a 32-byte seed (RFC 8032 5.1.5)."""
    seed = _check_bytes(seed, 32, "seed")
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return _encode(_multiply(scalar, BASE))


def sign(message: bytes, seed: bytes) -> bytes:
    """Return the 64-byte deterministic signature of message under seed."""
    seed = _check_bytes(seed, 32, "seed")
    if not isinstance(message, (bytes, bytearray)):
        raise ValueError("message must be bytes")
    message = bytes(message)
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    prefix = digest[32:]
    public = public_key(seed)
    nonce = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % L
    encoded_r = _encode(_multiply(nonce, BASE))
    challenge = int.from_bytes(
        hashlib.sha512(encoded_r + public + message).digest(), "little"
    ) % L
    scalar_s = (nonce + challenge * scalar) % L
    return encoded_r + scalar_s.to_bytes(32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature.

    A public key that is not 32 bytes is a programming error (ValueError);
    a malformed signature or point encoding simply fails verification.
    """
    public = _check_bytes(public, 32, "public key")
    if not isinstance(signature, (bytes, bytearray)) or len(signature) != 64:
        return False
    signature = bytes(signature)
    if not isinstance(message, (bytes, bytearray)):
        return False
    message = bytes(message)
    point_a = _decode(public)
    point_r = _decode(signature[:32])
    if point_a is None or point_r is None:
        return False
    scalar_s = int.from_bytes(signature[32:], "little")
    if scalar_s >= L:
        return False
    challenge = int.from_bytes(
        hashlib.sha512(signature[:32] + public + message).digest(), "little"
    ) % L
    left = _multiply(scalar_s, BASE)
    right = _add(point_r, _multiply(challenge, point_a))
    return _encode(left) == _encode(right)
