# voter_dashboard/services/vote_service.py
"""
Vote encryption/decryption service using Fernet symmetric encryption.

Security model:
  - Key is loaded from the environment (never hardcoded).
  - A new key can be generated once via `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 
    and stored in your .env file as VOTE_ENCRYPTION_KEY.
  - BinaryField stores raw bytes; memoryview is unwrapped before decryption.
  - All errors are caught and re-raised as VoteEncryptionError so callers
    receive a clean, loggable exception instead of a raw cryptography traceback.
"""

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


#  Custom exception 
class VoteEncryptionError(Exception):
    """Raised when vote encryption or decryption fails."""


#  Key loading
def _load_fernet() -> Fernet:
    """
    Load the Fernet instance from the environment.

    Raises:
        EnvironmentError: if VOTE_ENCRYPTION_KEY is missing or invalid.
    """
    raw_key = os.environ.get("VOTE_ENCRYPTION_KEY", "").strip()

    if not raw_key:
        raise EnvironmentError(
            "VOTE_ENCRYPTION_KEY is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            " and add it to your .env file."
        )

    try:
        return Fernet(raw_key.encode())
    except (ValueError, Exception) as exc:
        raise EnvironmentError(
            f"VOTE_ENCRYPTION_KEY is not a valid Fernet key: {exc}"
        ) from exc



try:
    _fernet = _load_fernet()
except EnvironmentError as _env_err:
    _fernet = None
    logger.critical("Vote encryption service failed to initialise: %s", _env_err)


#  Public API 

def encrypt_vote(vote: str) -> bytes:
    """
    Encrypt a plaintext vote string.

    Args:
        vote: The candidate name or vote identifier to encrypt.

    Returns:
        Fernet token as bytes, ready to be stored in BinaryField.

    Raises:
        VoteEncryptionError: if the service is misconfigured or encryption fails.
    """
    if _fernet is None:
        raise VoteEncryptionError(
            "Encryption service is not available. "
            "Check that VOTE_ENCRYPTION_KEY is set correctly."
        )
    if not isinstance(vote, str) or not vote.strip():
        raise VoteEncryptionError("Vote must be a non-empty string.")

    try:
        return _fernet.encrypt(vote.encode("utf-8"))
    except Exception as exc:
        logger.error("Failed to encrypt vote: %s", exc)
        raise VoteEncryptionError("Vote encryption failed.") from exc


def decrypt_vote(token: bytes | memoryview) -> str:
    """
    Decrypt a Fernet token back to the plaintext vote string.

    Django's BinaryField returns a memoryview, so we unwrap it first.

    Args:
        token: The encrypted bytes or memoryview from BinaryField.

    Returns:
        Plaintext vote string.

    Raises:
        VoteEncryptionError: if the token is invalid, tampered, or the
                             service is misconfigured.
    """
    if _fernet is None:
        raise VoteEncryptionError(
            "Encryption service is not available. "
            "Check that VOTE_ENCRYPTION_KEY is set correctly."
        )

    # Django BinaryField returns memoryview it onvert to bytes
    if isinstance(token, memoryview):
        token = bytes(token)

    if not token:
        raise VoteEncryptionError("Cannot decrypt an empty token.")

    try:
        return _fernet.decrypt(token).decode("utf-8")
    except InvalidToken:
        logger.warning("decrypt_vote received an invalid or tampered token.")
        raise VoteEncryptionError(
            "Vote token is invalid or has been tampered with."
        )
    except Exception as exc:
        logger.error("Unexpected decryption error: %s", exc)
        raise VoteEncryptionError("Vote decryption failed.") from exc