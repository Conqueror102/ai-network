from pydantic import SecretStr

from app.core.config import get_settings
from app.core.security import crypto


def test_old_rows_stay_readable_after_key_rotation(monkeypatch):
    s = get_settings()
    old_kid, old_key = s.msg_enc_kid, s.msg_enc_key
    before = crypto.encrypt("written with the old key")

    monkeypatch.setattr(s, "msg_enc_kid", "m2")
    monkeypatch.setattr(s, "msg_enc_key", SecretStr("ab" * 32))
    monkeypatch.setattr(s, "msg_enc_old_keys", {old_kid: old_key})

    after = crypto.encrypt("written with the new key")
    assert after.startswith("m2:") and before.startswith(f"{old_kid}:")
    assert crypto.decrypt(before) == "written with the old key"
    assert crypto.decrypt(after) == "written with the new key"
