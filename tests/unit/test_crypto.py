from app.utils import crypto


def test_generate_format_and_hash():
    full_key, prefix, key_hash = crypto.generate_api_key()
    assert crypto.KEY_RE.match(full_key)
    assert full_key.startswith(prefix + "_")
    assert len(prefix) == 12 and prefix.startswith("lgw_")
    assert len(full_key.split("_", 2)[2]) == 43
    assert len(key_hash) == 64
    assert key_hash == crypto.hash_api_key(full_key)
    assert full_key not in key_hash


def test_keys_are_unique():
    keys = {crypto.generate_api_key()[0] for _ in range(200)}
    assert len(keys) == 200


def test_verify():
    full_key, _, key_hash = crypto.generate_api_key()
    assert crypto.verify(full_key, key_hash)
    assert not crypto.verify(full_key + "x", key_hash)
    assert not crypto.verify(full_key, "0" * 64)


def test_hash_depends_on_pepper():
    full_key, _, _ = crypto.generate_api_key()
    assert crypto.hash_api_key(full_key, pepper=b"a" * 32) != crypto.hash_api_key(
        full_key, pepper=b"b" * 32
    )


def test_parse_key_prefix():
    full_key, prefix, _ = crypto.generate_api_key()
    assert crypto.parse_key_prefix(full_key) == prefix
    for bad in [
        "",
        "lgw_",
        "sk-abc",
        "lgw_ABCDEFGH_" + "a" * 43,
        "lgw_abcdefgh_short",
        "lgw_abcdefgh_" + "a" * 44,
        "Bearer " + full_key,
    ]:
        assert crypto.parse_key_prefix(bad) is None
