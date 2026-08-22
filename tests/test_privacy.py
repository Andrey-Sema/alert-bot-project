# noinspection PyPackageRequirements,PyUnresolvedReferences,SpellCheckingInspection
import hashlib
import hmac

from alert_bot_project.core_shared.config import config
from alert_bot_project.core_shared.privacy import hash_peer_id


class TestHashPeerId:
    def test_deterministic_for_same_id(self) -> None:
        assert hash_peer_id(12345) == hash_peer_id(12345)

    def test_differs_for_different_ids(self) -> None:
        assert hash_peer_id(12345) != hash_peer_id(54321)

    def test_output_is_16_hex_chars(self) -> None:
        result = hash_peer_id(999)
        assert len(result) == 16
        int(result, 16)  # не кидає ValueError лише якщо це валідний hex

    def test_never_returns_the_raw_id(self) -> None:
        peer_id = 777777777
        assert str(peer_id) not in hash_peer_id(peer_id)

    def test_falls_back_to_api_hash_when_app_secret_key_unset(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr(config, "APP_SECRET_KEY", "")
        expected = hmac.new(config.API_HASH.encode(), b"42", hashlib.sha256).hexdigest()[:16]
        assert hash_peer_id(42) == expected

    def test_uses_app_secret_key_when_set(self, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr(config, "APP_SECRET_KEY", "dedicated_test_salt")
        expected = hmac.new(b"dedicated_test_salt", b"42", hashlib.sha256).hexdigest()[:16]
        assert hash_peer_id(42) == expected

        # Змінена сіль повинна давати інший хеш, ніж дефолтний фолбек на API_HASH
        monkeypatch.setattr(config, "APP_SECRET_KEY", "")
        assert hash_peer_id(42) != expected
